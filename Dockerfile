# Use Python 3.11 as the base image
FROM python:3.11

# Set the working directory in the container
WORKDIR /app

# Clone the GitHub repository
RUN apt-get update && apt-get install -y git && \
    git clone https://github.com/FarlandDuck/wows-container-bot.git /app

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Run the bot
CMD ["python", "bot/main.py"]