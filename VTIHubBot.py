import asyncio
import logging
import argparse
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

# Configure basic logging to see bot's activity in the console
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def main():
    # Set up argument parser to securely receive the Telegram token via CLI
    parser = argparse.ArgumentParser(description="VTI Hub Ticket Bot on Aiogram 3")
    parser.add_argument('--token', required=True, help='Your Telegram Bot Token')
    args = parser.parse_args()

    # Initialize the Bot instance. 
    # DefaultBotProperties is the aiogram 3.x way to set default ParseMode for all messages
    bot = Bot(token=args.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    
    # Initialize the Dispatcher (it will route incoming updates to our handlers)
    dp = Dispatcher()

    logger.info("Starting bot...")

    # Start the polling process (bot starts listening to Telegram servers)
    try:
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"An error occurred during polling: {e}")
    finally:
        logger.info("Bot has been stopped.")

if __name__ == '__main__':
    # Run the main async loop
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # Graceful exit on Ctrl+C
        logger.info("Bot stopped by user (KeyboardInterrupt).")