import sys
import asyncio
import io

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import os
import requests
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ===== CONFIG =====
CPM1_API_KEY = "AIzaSyBW1ZbMiUeDZHYUO2bY8Bfnf5rRgrQGPTM"
CPM2_API_KEY = "AIzaSyCQDz9rgjgmvmFkvVfmvr2-7fT4tfrzRRQ"
BOT_TOKEN = "8664082287:AAHri0WpzqQbtT3bkhjctl5PTEvUiSORfqU"

# ===== CPM FUNCTIONS =====
def login_request(email, password, api_key):
    url = f"https://www.googleapis.com/identitytoolkit/v3/relyingparty/verifyPassword?key={api_key}"
    payload = {"email": email, "password": password, "returnSecureToken": True}
    response = requests.post(url, json=payload)
    return response.json()

def update_request(id_token, api_key, new_email=None, new_password=None):
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:update?key={api_key}"
    payload = {"idToken": id_token, "returnSecureToken": True}
    if new_email: payload["email"] = new_email
    if new_password: payload["password"] = new_password
    response = requests.post(url, json=payload)
    return response.json()

# ==== START FUNCTION =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✨ Welcome to Ash Change Tool Bot ✨\nUse /secure to start bulk update.")

# ----- MESSAGE HANDLER -----
async def secure_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["step"] = "secure_accounts_file"
    await update.message.reply_text("Please upload the file containing accounts (format: email:password per line).")

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    step = context.user_data.get("step")

    if step == "secure_accounts_file" and document:
        file_id = document.file_id
        new_file = await context.bot.get_file(file_id)
        file_path = await new_file.download_to_drive()
        context.user_data["accounts_file_path"] = str(file_path)
        context.user_data["step"] = "secure_targets_file"
        await update.message.reply_text("Accounts file received. Now, please upload the file containing target credentials (format: new_email:new_password per line). Note: Targets will be applied sequentially to successful logins.")
        return
    elif step == "secure_targets_file" and document:
        file_id = document.file_id
        new_file = await context.bot.get_file(file_id)
        file_path = await new_file.download_to_drive()
        context.user_data["targets_file_path"] = str(file_path)
        context.user_data["step"] = "processing_secure_bulk"
        await update.message.reply_text("Target credentials file received. Processing bulk update...")
        await process_bulk_update(update, context)
        return
    else:
        await update.message.reply_text("Please use the /secure command to initiate bulk updates and upload files as requested.")

async def process_bulk_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    accounts_file_path = context.user_data.get("accounts_file_path")
    targets_file_path = context.user_data.get("targets_file_path")

    if not accounts_file_path or not targets_file_path:
        await update.message.reply_text("Error: Account or target file not found. Please restart with /secure.")
        context.user_data.clear()
        return

    accounts = []
    targets = []
    results = []

    try:
        # Parse accounts file (email:password)
        with open(accounts_file_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line: continue
                parts = line.split(":")
                if len(parts) >= 2:
                    # Rejoin in case password contains ":"
                    accounts.append({"email": parts[0], "password": ":".join(parts[1:])})
                else:
                    results.append(f"Skipping malformed account line: {line}")

        # Parse targets file (new_email:new_password)
        with open(targets_file_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line: continue
                parts = line.split(":")
                if len(parts) >= 2:
                    targets.append({"new_email": parts[0], "new_password": ":".join(parts[1:])})
                else:
                    results.append(f"Skipping malformed target line: {line}")

        if not accounts:
            await update.message.reply_text("No valid accounts found in the accounts file.")
            context.user_data.clear()
            return
        if not targets:
            await update.message.reply_text("No valid targets found in the targets file.")
            context.user_data.clear()
            return

        await update.message.reply_text(f"Processing {len(accounts)} accounts and {len(targets)} target changes...")

        target_index = 0
        for account in accounts:
            if target_index >= len(targets):
                results.append("Ran out of target credentials. Stopping further updates.")
                break

            email = account["email"]
            password = account["password"]

            # Try login with CPM1 first, then CPM2
            api_key = CPM1_API_KEY
            game_name = "CPM1"
            login_resp = login_request(email, password, api_key)
            
            if "idToken" not in login_resp:
                # Try CPM2
                api_key = CPM2_API_KEY
                game_name = "CPM2"
                login_resp = login_request(email, password, api_key)

            if "idToken" not in login_resp:
                error_msg = login_resp.get("error", {}).get("message", "Unknown error")
                results.append(f"❌ Login failed for {email}: {error_msg}")
                continue

            id_token = login_resp["idToken"]
            
            # Get next target
            target_change = targets[target_index]
            new_email = target_change["new_email"]
            new_password = target_change["new_password"]

            # Update credentials
            change_resp = update_request(id_token, api_key, new_email=new_email, new_password=new_password)
            if "idToken" in change_resp or "email" in change_resp:
                results.append(f"✅ Updated {email} to {new_email}:{new_password} ({game_name})")
                target_index += 1 # Move to next target only on success
            else:
                error_msg = change_resp.get("error", {}).get("message", "Unknown error")
                results.append(f"❌ Failed to update {email} ({game_name}): {error_msg}")

    except Exception as e:
        results.append(f"An error occurred during bulk processing: {e}")

    finally:
        # Clean up files
        if os.path.exists(accounts_file_path):
            os.remove(accounts_file_path)
        if os.path.exists(targets_file_path):
            os.remove(targets_file_path)
        context.user_data.clear()

    # Send results back to user
    result_text = "\n".join(results)
    if len(result_text) > 4000: # Telegram message limit
        with io.StringIO() as output_file:
            output_file.write(result_text)
            output_file.seek(0)
            await update.message.reply_document(output_file, filename="bulk_update_results.txt", caption="Bulk update results (too long for message):")
    else:
        await update.message.reply_text("Bulk update complete:\n" + result_text)

# ===== BOT STARTUP =====
app = Application.builder().token(BOT_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("secure", secure_command))
app.add_handler(MessageHandler(filters.Document.ALL, handle_document))

print("🚀 Bot is running...")
app.run_polling()
