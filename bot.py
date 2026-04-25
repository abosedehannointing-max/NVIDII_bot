import os
import logging
import io
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from openai import OpenAI
import requests

# Enable logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize OpenAI client (reads OPENAI_API_KEY from environment)
openai_client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

# Store user states (in production, use Redis or database)
user_sessions = {}

# Image size presets for Instagram
SIZE_PRESETS = {
    'square': '1024x1024',      # 1:1 - Standard post
    'portrait': '1024x1792',    # 4:5 - Vertical post
    'landscape': '1792x1024',   # 16:9 - Landscape
    'story': '1080x1920'        # 9:16 - Instagram Story
}

# Size display names for user messages
SIZE_NAMES = {
    'square': 'Square (1:1)',
    'portrait': 'Portrait (4:5)',
    'landscape': 'Landscape (16:9)',
    'story': 'Story (9:16)'
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send welcome message when /start is issued."""
    welcome_msg = (
        "🎨 *AI Image Generator Bot for Instagram*\n\n"
        "I can create stunning images for your Instagram posts using AI!\n\n"
        "*Commands:*\n"
        "/generate - Create a new image\n"
        "/help - Show help message\n"
        "/presets - View available image sizes\n"
        "/cancel - Cancel current operation\n\n"
        "*How to use:*\n"
        "1. Send /generate\n"
        "2. Describe the image you want\n"
        "3. Choose aspect ratio\n"
        "4. Receive your AI-generated image!\n\n"
        "*Example prompts:*\n"
        "• 'Aesthetic coffee shop interior with warm lighting'\n"
        "• 'Minimalist quote background with pastel colors'\n"
        "• 'Fitness motivation scene with weights'\n\n"
        "Ready? Type /generate to begin! 🚀"
    )
    await update.message.reply_text(welcome_msg, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send detailed help message."""
    help_msg = (
        "*📖 Detailed Help Guide*\n\n"
        "*How to generate an image:*\n"
        "1️⃣ Type /generate\n"
        "2️⃣ Describe your image (be specific!)\n"
        "3️⃣ Choose your preferred size\n"
        "4️⃣ Wait 10-20 seconds\n\n"
        "*Best practices for prompts:*\n"
        "✅ Be specific: 'A serene mountain lake at sunset, photorealistic'\n"
        "✅ Include style: 'Minimalist, vibrant colors, cinematic lighting'\n"
        "✅ Add mood: 'Peaceful, energetic, mysterious, romantic'\n"
        "✅ Mention Instagram: 'Instagram-worthy, aesthetic, viral style'\n\n"
        "*Example prompts:*\n"
        "• 'Cozy reading nook with warm fairy lights, book and coffee, aesthetic vibe'\n"
        "• 'Futuristic city skyline at night, neon purple and blue, cyberpunk style'\n"
        "• 'Motivational quote background with golden hour lighting and soft bokeh'\n\n"
        "*Common issues:*\n"
        "• If generation fails, try a shorter prompt (under 200 characters)\n"
        "• Avoid special characters or emojis in prompts\n"
        "• Use /cancel if the bot stops responding to you\n"
    )
    await update.message.reply_text(help_msg, parse_mode='Markdown')

async def presets_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show available image size presets."""
    presets_msg = (
        "*📐 Instagram Image Sizes*\n\n"
        "• *Square* - 1024×1024 (1:1)\n"
        "  Best for: Standard feed posts, product photos\n\n"
        "• *Portrait* - 1024×1792 (4:5)\n"
        "  Best for: Vertical feed posts, quotes, portraits\n\n"
        "• *Landscape* - 1792×1024 (16:9)\n"
        "  Best for: Horizontal/landscape photos, scenery\n\n"
        "• *Story* - 1080×1920 (9:16)\n"
        "  Best for: Instagram Stories, Reels covers\n\n"
        "*Pro tip:* Most mobile users prefer portrait (4:5) as it takes up more screen space!\n\n"
        "You'll be prompted to choose a size when using /generate."
    )
    await update.message.reply_text(presets_msg, parse_mode='Markdown')

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel ongoing operation."""
    user_id = update.effective_user.id
    if user_id in user_sessions:
        del user_sessions[user_id]
        await update.message.reply_text("✅ Operation cancelled. Use /generate to start over.")
    else:
        await update.message.reply_text("ℹ️ No active operation to cancel. Use /generate to create an image!")

async def generate_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the image generation process."""
    user_id = update.effective_user.id
    
    # Initialize user session
    user_sessions[user_id] = {'step': 'awaiting_prompt'}
    
    await update.message.reply_text(
        "🎨 *Let's create an Instagram-worthy image!*\n\n"
        "*Step 1 of 2:* Describe your image\n\n"
        "Be specific about:\n"
        "• What you want to see (objects, people, scenery)\n"
        "• Style (realistic, artistic, minimal, vibrant)\n"
        "• Mood (calm, energetic, dreamy, professional)\n"
        "• Colors (warm, cool, pastel, neon)\n\n"
        "*Example:* 'A cozy coffee shop interior with warm lighting, a latte with latte art, aesthetic Instagram style, soft bokeh background'\n\n"
        "✏️ Send your description now:",
        parse_mode='Markdown'
    )

async def handle_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the user's image prompt."""
    user_id = update.effective_user.id
    user_message = update.message.text
    
    # Check if user is in generation flow
    if user_id not in user_sessions or user_sessions[user_id].get('step') != 'awaiting_prompt':
        await update.message.reply_text(
            "Please use /generate to start creating an image first."
        )
        return
    
    # Validate prompt length
    if len(user_message) > 500:
        await update.message.reply_text(
            "⚠️ Your prompt is too long (max 500 characters). Please make it shorter and try again.\n\n"
            "Use /cancel to start over."
        )
        return
    
    # Store the prompt
    user_sessions[user_id]['prompt'] = user_message
    user_sessions[user_id]['step'] = 'awaiting_size'
    
    # Create inline keyboard for size selection
    keyboard = [
        [InlineKeyboardButton("⬛ Square (1:1) - Standard post", callback_data='square')],
        [InlineKeyboardButton("📱 Portrait (4:5) - Vertical feed", callback_data='portrait')],
        [InlineKeyboardButton("🌄 Landscape (16:9) - Horizontal", callback_data='landscape')],
        [InlineKeyboardButton("📖 Story (9:16) - Instagram Stories", callback_data='story')],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"✅ *Prompt received!*\n\n"
        f"📝 *Your description:*\n\"{user_message[:200]}{'...' if len(user_message) > 200 else ''}\"\n\n"
        f"*Step 2 of 2:* Choose your aspect ratio\n\n"
        f"Select the size that best fits your Instagram post:",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )

async def handle_size_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the size selection callback and generate the image."""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    size_choice = query.data
    
    # Validate session
    if user_id not in user_sessions or 'prompt' not in user_sessions[user_id]:
        await query.edit_message_text(
            "❌ Session expired or not found. Please start over with /generate"
        )
        return
    
    # Get the selected size
    size_dimensions = SIZE_PRESETS.get(size_choice, SIZE_PRESETS['square'])
    width, height = map(int, size_dimensions.split('x'))
    
    # Store in session
    user_sessions[user_id]['size'] = size_choice
    user_sessions[user_id]['dimensions'] = (width, height)
    
    # Send processing message
    await query.edit_message_text(
        f"🎨 *Generating your image...*\n\n"
        f"📝 *Prompt:* {user_sessions[user_id]['prompt'][:100]}...\n"
        f"📐 *Size:* {SIZE_NAMES.get(size_choice, size_choice)} ({width}×{height})\n\n"
        f"⏳ This takes 10-20 seconds. Please wait...\n\n"
        f"⚠️ *Don't send any messages* until the image appears!",
        parse_mode='Markdown'
    )
    
    try:
        # Generate image using DALL-E 3
        image_url = await generate_image(
            prompt=user_sessions[user_id]['prompt'],
            size_choice=size_choice
        )
        
        # Download the image
        image_data = await download_image(image_url)
        
        # Prepare caption
        caption = (
            f"✨ *Your Instagram image is ready!*\n\n"
            f"📝 *Prompt:* {user_sessions[user_id]['prompt'][:150]}\n"
            f"📐 *Size:* {SIZE_NAMES.get(size_choice, size_choice)}\n\n"
            f"💡 *Instagram Tips:*\n"
            f"• Save this image to your phone/computer\n"
            f"• Use in feed post, story, or reel\n"
            f"• Add your caption and hashtags\n\n"
            f"🎨 *Want another?* Send /generate again!"
        )
        
        # Send the image to user
        await query.message.reply_photo(
            photo=image_data,
            caption=caption,
            parse_mode='Markdown'
        )
        
        # Clean up session
        if user_id in user_sessions:
            del user_sessions[user_id]
        
        logger.info(f"Successfully generated image for user {user_id}")
        
    except Exception as e:
        logger.error(f"Error generating image for user {user_id}: {e}")
        error_message = str(e)
        
        # User-friendly error messages
        if "rate_limit" in error_message.lower():
            error_text = "⏰ Rate limit exceeded. Please wait a minute and try again."
        elif "invalid_api_key" in error_message.lower():
            error_text = "🔑 API configuration error. Please contact support."
        elif "billing" in error_message.lower():
            error_text = "💳 Service temporarily unavailable. Please try again later."
        else:
            error_text = f"❌ Failed to generate image: {error_message[:200]}\n\nPlease try:\n• Shorter prompt (under 200 characters)\n• Different size\n• Use /generate to start over"
        
        await query.message.reply_text(error_text)
        
        # Clean up session on error
        if user_id in user_sessions:
            del user_sessions[user_id]

async def generate_image(prompt: str, size_choice: str) -> str:
    """Generate image using OpenAI DALL-E 3 API."""
    
    # Map size_choice to DALL-E 3 supported sizes
    # DALL-E 3 only supports: 1024x1024, 1024x1792, 1792x1024
    size_map = {
        'square': "1024x1024",
        'portrait': "1024x1792",
        'landscape': "1792x1024",
        'story': "1024x1792"  # Story uses portrait size, user can crop
    }
    
    api_size = size_map.get(size_choice, "1024x1024")
    
    # Enhance prompt for better Instagram results
    enhanced_prompt = (
        f"Create a high-quality, Instagram-worthy image: {prompt}. "
        f"Make it visually appealing, well-composed, with good lighting and colors. "
        f"Suitable for social media posting."
    )
    
    try:
        response = openai_client.images.generate(
            model="dall-e-3",
            prompt=enhanced_prompt,
            size=api_size,
            quality="standard",
            n=1,
        )
        
        return response.data[0].url
        
    except Exception as e:
        logger.error(f"OpenAI API error: {e}")
        raise

async def download_image(url: str) -> io.BytesIO:
    """Download image from URL and return as BytesIO object."""
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        # Convert to BytesIO
        image_bytes = io.BytesIO(response.content)
        image_bytes.seek(0)
        
        return image_bytes
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to download image: {e}")
        raise Exception("Failed to download generated image")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors gracefully."""
    logger.error(f"Update {update} caused error {context.error}")
    
    # Try to notify user if possible
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "⚠️ An unexpected error occurred. Please try again later.\n\n"
            "If the problem persists, use /cancel and start over with /generate"
        )

def main():
    """Start the bot."""
    # Get token from environment variable
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        logger.error("❌ TELEGRAM_BOT_TOKEN not found in environment variables!")
        logger.error("Please set it in Render dashboard: Environment Variables")
        return
    
    # Verify OpenAI API key is set
    if not os.getenv('OPENAI_API_KEY'):
        logger.error("❌ OPENAI_API_KEY not found in environment variables!")
        logger.error("Please set it in Render dashboard: Environment Variables")
        return
    
    logger.info("✅ Environment variables loaded successfully")
    
    # Create application
    application = Application.builder().token(token).build()
    
    # Add command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("presets", presets_command))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(CommandHandler("generate", generate_command))
    
    # Add message handler for prompts (only when not commands)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_prompt))
    
    # Add callback query handler for size selection
    application.add_handler(CallbackQueryHandler(handle_size_selection))
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Start the bot
    logger.info("🚀 Bot is starting...")
    
    # Fix for Python 3.14 event loop issue
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    # Run the bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
