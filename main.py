import discord
from dotenv import load_dotenv
import os
def configure():
    load_dotenv()


class Client(discord.Client):
    async def on_ready(self):
        print(f'Logged on as {self.user}!')

    async def on_message(self, message):
        print(f'Message from {message.author}: {message.content}')

def main():
    configure()
    intents = discord.Intents.default()
    intents.message_content = True

    client = Client(intents = intents)
    client.run(os.getenv('api_key'))

main()