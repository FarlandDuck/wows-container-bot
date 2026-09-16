import os
import discord
import random
import json
import difflib
import io
from discord.ext import commands
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
from datetime import datetime


TOKEN = os.getenv('DISCORD_TOKEN')

# Setup intents
intents = discord.Intents.default()
intents.message_content = True

# Create bot instance without the default help command
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

# Directory where container JSON files are stored
CONTAINER_FOLDER = "containers"

# Load all container data dynamically
container_data = {}

for filename in os.listdir(CONTAINER_FOLDER):
    if filename.endswith(".json"):  # Only process JSON files
        file_path = os.path.join(CONTAINER_FOLDER, filename)
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            container_data[data["nickname"].lower()] = data  # Store by lowercase nickname for easy lookup

# Bot Ready Event
@bot.event
async def on_ready():
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f'[{timestamp}] {bot.user.name} has connected to Discord!')

# Custom Help Command
@bot.command(name="help")
async def custom_help(ctx):
    """Provides a cleaner help message."""
    embed = discord.Embed(
        title="Available Commands",
        description="Here are the available commands for the bot:",
        color=discord.Color.blue()
    )
    embed.add_field(name="`!collection [total items] [owned items] [tokens owned] [duplicates owned] [conversion rate]`", value="Calculates the exact number of containers needed to complete a collection.", inline=False)
    embed.add_field(name="`!open [container name]`", value="Opens a container and gives a random drop.", inline=False)
    embed.add_field(name="`!info`", value="Lists all available containers.", inline=False)
    embed.add_field(name="`!help`", value="Displays this help message.", inline=False)

    await ctx.send(embed=embed)


def exact_collection_pmf(n, k, t0, d0, c):
    """
    Computes the EXACT probability distribution of the number of containers
    needed to complete a collection, via an absorbing Markov chain, instead
    of a Monte Carlo simulation.

    Model
    -----
    Let e = number of empty (uncollected) slots remaining. Each draw hits an
    empty slot with probability e/n (a "new item") or an already-owned slot
    with probability (n-e)/n (a "duplicate"). Because slots are symmetric,
    the exact set of which slots are owned never matters -- only the count e
    does -- so e (together with the running duplicate/token counters) is a
    sufficient state for an exact Markov chain, with no need to sample.

    Since duplicates always convert into tokens deterministically (d0+s
    duplicates drawn so far always yields the same tokens/leftover-duplicates
    via divmod by c, regardless of the order new-item vs. duplicate draws
    happened in), the pair (e, s) -- where s = cumulative duplicate draws
    so far -- fully determines the state:
        d(s) = (d0 + s) % c
        t(s) = t0 + (d0 + s) // c
    This collapses the (e, d, t) state space down to just (e, s), which is
    walked forward step-by-step (a draw either decreases e by 1, or
    increases s by 1), tracking the probability mass at each reachable
    state. Whenever a state's t(s) >= e (mirroring the original loop's
    `if tokens >= empties: break`), that probability mass is absorbed into
    the output PMF at the current step count m.

    Because t(s) is non-decreasing and unbounded as s grows, for any fixed e
    there's always a finite s beyond which t(s) >= e is guaranteed
    deterministically -- so this process is guaranteed to fully absorb
    (PMF sums to exactly 1.0) after a finite number of steps.

    Returns
    -------
    dict {m: probability} for m = 0, 1, 2, ... (m = containers opened)
    """
    e0 = n - k
    if e0 <= 0:
        return {0: 1.0}

    alive = {e0: 1.0}  # key: e : probability mass; s is implied by (m, e)
    m = 0
    pmf = {}

    while alive:
        m += 1
        new_alive = {}
        for e, p in alive.items():
            s = (m - 1) - e0 + e  # cumulative duplicate draws so far, before this draw
            p_new = e / n
            p_dup = (n - e) / n

            # Draw a NEW item: e decreases by 1, s unchanged.
            if p_new > 0:
                e_n, s_n = e - 1, s
                t_n = t0 + (d0 + s_n) // c
                prob = p * p_new
                if t_n >= e_n:
                    pmf[m] = pmf.get(m, 0.0) + prob
                else:
                    new_alive[e_n] = new_alive.get(e_n, 0.0) + prob

            # Draw a DUPLICATE: e unchanged, s increases by 1.
            if p_dup > 0:
                e_d, s_d = e, s + 1
                t_d = t0 + (d0 + s_d) // c
                prob = p * p_dup
                if t_d >= e_d:
                    pmf[m] = pmf.get(m, 0.0) + prob
                else:
                    new_alive[e_d] = new_alive.get(e_d, 0.0) + prob

        alive = new_alive

    return pmf


def pmf_to_exact_staircase(pmf):
    """
    Builds the exact quantile-function staircase from the PMF's CDF, rather than
    interpolating between a handful of sampled percentiles. The number of
    containers needed is always a whole number, so the true quantile function
    is a step function; plotting it this way (a horizontal segment at height m
    from the percentile where m becomes achievable to the percentile where the
    next value takes over, then a vertical jump) draws that step shape exactly,
    with no diagonal-line artifacts from sparse sampling.
    """
    xs, ys = [], []
    prev_cdf = 0.0
    for m in sorted(pmf.keys()):
        cdf_m = prev_cdf + pmf[m]
        xs.extend([prev_cdf * 100, cdf_m * 100])
        ys.extend([m, m])
        prev_cdf = cdf_m
    xs[-1] = 100.0  # guard against float drift so the curve lands exactly at 100
    return xs, ys


def pmf_mean(pmf):
    return sum(m * p for m, p in pmf.items())


def pmf_median(pmf):
    """Smallest m such that CDF(m) >= 0.5 (the exact median of the distribution)."""
    cdf = 0.0
    for m in sorted(pmf.keys()):
        cdf += pmf[m]
        if cdf >= 0.5:
            return m
    return max(pmf.keys())


# Rough estimate of World of Warships' active playerbase, used only to decide
# what counts as a "realistic" outcome to display. WG doesn't publish exact
# figures; independent estimates of monthly active players across all
# platforms (Steam + the Wargaming client, which most players use) land
# roughly in the hundreds-of-thousands-to-low-millions range, so 1,000,000
# is a reasonable round anchor. This is a display choice, not a precise
# population count -- feel free to tune it.
ASSUMED_PLAYERBASE = 1_000_000

# How confident we want to be that NOT A SINGLE player in the whole assumed
# playerbase ever lands outside the displayed [Min, Max]. This is a genuine
# trade-off, not a free lunch: the true min/max already have the property
# that literally nobody can go outside them (probability exactly zero
# beyond the support of the distribution). Any narrower range necessarily
# accepts some nonzero risk that a real player eventually falls outside it
# -- higher CONFIDENCE demands a wider (safer) range, approaching the true
# min/max as CONFIDENCE -> 100%. 99.9% is a strong, practically-certain bar
# while still meaningfully excluding the truly astronomical tail.
CONFIDENCE_NO_EXCEEDANCE = 0.999


def realistic_bounds(pmf, playerbase=ASSUMED_PLAYERBASE, confidence=CONFIDENCE_NO_EXCEEDANCE):
    """
    Chooses the tightest [Min, Max] such that the probability of at least one
    player, out of `playerbase` independent players, ever landing outside
    [Min, Max] is at most (1 - confidence).

    For a single player, P(outside bounds) = p. Across N independent players,
    P(nobody is outside) = (1-p)^N. We want (1-p)^N >= per-tail confidence,
    i.e. p <= 1 - (per_tail_epsilon)^(1/N), which is the exact (not just
    epsilon/N approximated) per-player probability threshold. The total
    allowed failure probability (1-confidence) is split evenly between the
    lower and upper tail.
    """
    epsilon_tail = (1 - confidence) / 2
    p_tail = 1 - epsilon_tail ** (1.0 / playerbase)

    ms = sorted(pmf.keys())

    cdf = 0.0
    low = ms[0]
    for m in ms:
        cdf += pmf[m]
        if cdf >= p_tail:
            low = m
            break

    cdf2 = 0.0
    high = ms[-1]
    for m in reversed(ms):
        cdf2 += pmf[m]
        if cdf2 >= p_tail:
            high = m
            break

    return low, high


# Command: Collection Simulation (now computed exactly, no sampling)
@bot.command(name="collection")
async def collection(ctx, n: int = None, k: int = None, t: int = None, d: int = None, c: int = None):
    """Computes the exact number of containers needed to complete a collection.

    n = total items in the collection
    k = items already owned
    t = collection tokens already banked
    d = duplicates owned toward the next token (should be less than c, since
        the game auto-exchanges duplicates into tokens once the rate is hit)
    c = duplicates required per token (conversion/exchange rate)
    """

    # If no arguments provided, show usage instruction
    if n is None or k is None or t is None or d is None or c is None:
        await ctx.send("Usage: `!collection [total items] [owned items] [tokens owned] [duplicates owned] [conversion rate]`")
        return

    if n > 100 or n <= 0 or k > n or k < 0 or t < 0 or d < 0 or c <= 0:
        await ctx.send("Invalid input values. Please check the command usage.")
        return

    if d >= c:
        await ctx.send(f"Duplicates owned ({d}) should be less than the conversion rate ({c}), since duplicates auto-exchange into tokens once they hit that number. Did you mean to include those extra tokens in the tokens owned value instead?")
        return

    # Exact PMF via absorbing Markov chain -- replaces the old 100k-run Monte Carlo.
    pmf = exact_collection_pmf(n, k, t, d, c)
    xs, ys = pmf_to_exact_staircase(pmf)
    mean_containers = pmf_mean(pmf)

    # Generate the plot
    plt.figure(figsize=(10, 5))
    plt.plot(xs, ys, label="Number of Containers Needed (exact)", color='b')
    plt.xlabel("Percentile of Players")
    plt.ylabel("Number of Containers Opened")
    plt.title("Containers Needed to Complete a Collection by Percentile")
    plt.grid(True)
    plt.legend()

    # X-axis anchored to fixed 0/20/40/60/80/100 percentile marks
    ax = plt.gca()
    ax.set_xlim(-5, 105)
    ax.set_xticks([0, 20, 40, 60, 80, 100])
    # Y-axis: whole-number container counts only
    ax.yaxis.set_major_locator(mticker.MaxNLocator(integer=True))

    # Add contextual information in a box (bottom-right)
    info_text = (
        f"Total Items in Collection: {n}\n"
        f"Items Owned: {k}\n"
        f"Tokens Owned: {t}\n"
        f"Duplicates Owned: {d}\n"
        f"Conversion Rate: {c}"
    )
    plt.annotate(
        info_text,
        xy=(0.98, 0.02), xycoords='axes fraction',
        fontsize=10, color='black', ha='right', va='bottom',
        bbox=dict(boxstyle="round,pad=0.5", edgecolor='black', facecolor='white')
    )

    # Separate box (top-left, not the legend) for min / max / mean containers.
    # Min/Max are trimmed to realistic outcomes (see realistic_bounds) rather
    # than the literal, astronomically-rare best/worst case the exact chain
    # still technically assigns nonzero probability to.
    min_containers, max_containers = realistic_bounds(pmf)
    median_containers = pmf_median(pmf)
    stats_text = (
        f"Min: {min_containers} Containers\n"
        f"Max: {max_containers} Containers\n"
        f"Mean: {mean_containers:.2f} Containers\n"
        f"Median: {median_containers} Containers"
    )
    plt.annotate(
        stats_text,
        xy=(0.02, 0.98), xycoords='axes fraction',
        fontsize=10, color='black', ha='left', va='top',
        bbox=dict(boxstyle="round,pad=0.5", edgecolor='black', facecolor='white')
    )

    # Save the plot to a BytesIO object
    img_buffer = io.BytesIO()
    plt.savefig(img_buffer, format='png', bbox_inches='tight')
    img_buffer.seek(0)

    # Close the plot
    plt.close()

    # Create a file to send as an attachment
    file = discord.File(img_buffer, filename="collection_exact.png")

    # Send only the image file
    await ctx.send(file=file)

# Command: Info
@bot.command(name="info")
async def info(ctx):
    """Lists available containers."""
    await ctx.send(f"Use `!open [container name]`. Available containers: {', '.join(sorted(container_data.keys()))}")

def process_drop_pool(drop_pool):
    """
    Recursively processes a drop pool and returns the final selected item.
    """
    roll = random.uniform(0, 100)
    
    # Check if drop pool uses custom rates
    if "rate" in drop_pool[0]:
        cumulative_rate = 0
        selected_drop = None
        for drop in drop_pool:
            cumulative_rate += drop["rate"]
            if roll <= cumulative_rate:
                selected_drop = drop
                break
        if selected_drop is None:  # Fallback in case of rounding errors
            selected_drop = drop_pool[-1]
    else:
        # Even distribution
        selected_drop = random.choice(drop_pool)
    
    # If the selected drop has sub-drops (nested pool), continue traversal
    if "drops" in selected_drop:
        return process_drop_pool(selected_drop["drops"])
    else:
        return selected_drop

# Command: Open Container
@bot.command(name="open")
async def open_container(ctx, *, container_name: str = None):
    """Simulates opening a container and getting a random drop."""

    # If no container name is provided
    if container_name is None:
        await ctx.send("Usage: `!open [container_name]`\nUse `!info` to see available containers.")
        return

    # Find best matching container name
    matched_name = difflib.get_close_matches(container_name.lower(), container_data.keys(), n=1, cutoff=0)
    if not matched_name:
        await ctx.send("Invalid container name. Use `!info` to see available containers.")
        return

    container = container_data[matched_name[0]]

    # Embed for Discord message
    embed = discord.Embed(title=container["name"], color=discord.Color.from_str(container["color"]))

    # Set container thumbnail if available
    if "image" in container and container["image"]:
        embed.set_thumbnail(url=container["image"])

    # Check if container uses the new "slots" structure or legacy "drops" structure
    if "slots" in container:
        # Multi-slot container
        all_drops = []
        
        for slot_index, slot in enumerate(container["slots"]):
            selected_drop = process_drop_pool(slot["drops"])
            all_drops.append(selected_drop)
        
        # First slot gets the image embed, rest are text
        if all_drops:
            # Set description with all drop names
            drop_names = [drop["name"] for drop in all_drops]
            embed.description = ", ".join(drop_names)
            
            # Set image from first slot if available
            if "link" in all_drops[0] and all_drops[0]["link"]:
                embed.set_image(url=all_drops[0]["link"])
        
        # Log the opening event
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        drops_str = ", ".join([drop["name"] for drop in all_drops])
        print(f"[{timestamp}] {ctx.author} opened '{container['nickname']}' and received '{drops_str}'.")
        
    else:
        # Legacy single-slot container
        selected_drop = process_drop_pool(container["drops"])
        
        embed.description = selected_drop["name"]
        if "link" in selected_drop and selected_drop["link"]:
            embed.set_image(url=selected_drop["link"])
        
        # Log the opening event
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] {ctx.author} opened '{container['nickname']}' and received '{selected_drop['name']}'.")

    await ctx.send(embed=embed)

# Run the bot
bot.run(TOKEN)