from dotenv import load_dotenv
import os
import asyncio
import pyodbc
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ConversationHandler
from telegram.helpers import escape_markdown

load_dotenv()
logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("BOT_TOKEN")
conn_str = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=EMILBAD;"
    "DATABASE=MedicineDatabase;"
    "Trusted_Connection=yes;"
)

ADD_NAME, ADD_ATTR = range(2)

SEARCHING_MEDICINE = "searching_medicine"
ADD_MEDICINE = "add_medicine"

ATTRIBUTES = {
    "Name": "Название",
    "InternationalName": "Международное название",
    "ATCCode": "Код АТХ",
    "DosageForm": "Лекарственная форма",
    "ActiveSubstances": "Действующие вещества",
    "Composition": "Состав",
    "Indications": "Показания к применению",
    "IndicationsForChildren": "Показания для детей",
    "Contraindications": "Противопоказания",
    "SideEffects": "Побочные эффекты",
    "Dosage": "Рекомендации по дозировке",
    "Overdose": "Передозировка",
    "PregnancyAndLactation": "Применение при беременности и лактации",
    "ApplicationInChildren": "Применение у детей",
    "ApplicationInRenalFailure": "Применение при почечной недостаточности",
    "ApplicationInHepaticFailure": "Применение при печеночной недостаточности",
    "SpecialInstructions": "Особые указания",
    "DrugInteractions": "Взаимодействие с другими лекарствами",
    "BudgetAlternatives": "Бюджетные аналоги",
    "InformationSource": "Источник информации"
}


async def get_db_connection():
    try:
        return await asyncio.to_thread(pyodbc.connect, conn_str)
    except pyodbc.Error:
        return None

async def search_medicine_by_name(name_part: str):
    conn = await get_db_connection()
    if not conn:
        return None
    
    try:
        cursor = conn.cursor()
        query = "SELECT Name FROM Medicines WHERE Name LIKE ?"
        cursor.execute(query, (f"%{name_part}%",))
        rows = cursor.fetchall()
        return [row.Name for row in rows]
    finally:
        conn.close()

async def get_medicine_details(name: str):
    conn = await get_db_connection()
    if not conn:
        return None
    
    try:
        cursor = conn.cursor()
        query = "SELECT * FROM Medicines WHERE Name = ?"
        cursor.execute(query, (name,))
        return cursor.fetchone()
    finally:
        conn.close()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[KeyboardButton("🔍 Поиск лекарства")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text("Привет! Нажмите '🔍 Поиск лекарства' для начала поиска.", reply_markup=reply_markup)

async def request_medicine_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Введите название лекарства:")
    context.user_data[SEARCHING_MEDICINE] = True

    
async def receive_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["new_medicine"]["Name"] = update.message.text
    return await ask_next_attribute(update, context)

async def ask_next_attribute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    attr_list = context.user_data["attr_list"]
    index = context.user_data["current_attr"]

    if index >= len(attr_list):
        return await save_medicine(update, context)

    attr = attr_list[index]
    rus_attr = ATTRIBUTES[attr]

    keyboard = [
        [InlineKeyboardButton("Назад", callback_data="back")],
        [InlineKeyboardButton("Отмена", callback_data="cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if update.callback_query:
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(f"Введите значение для '{rus_attr}':", reply_markup=reply_markup)
    else:
        await update.message.reply_text(f"Введите значение для '{rus_attr}':", reply_markup=reply_markup)

    return ADD_ATTR

async def add_attribute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    attr_list = context.user_data["attr_list"]
    index = context.user_data["current_attr"]
    attr = attr_list[index]

    context.user_data["new_medicine"][attr] = update.message.text  
    context.user_data["current_attr"] += 1 

    return await ask_next_attribute(update, context)

async def add_attribute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    attr_list = context.user_data["attr_list"]
    index = context.user_data["current_attr"]
    attr = attr_list[index]

    context.user_data["new_medicine"][attr] = update.message.text
    context.user_data["current_attr"] += 1

    return await ask_next_attribute(update, context)

async def save_medicine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    new_medicine = context.user_data["new_medicine"]

    columns = ", ".join(new_medicine.keys())
    values = ", ".join("?" for _ in new_medicine)
    query = f"INSERT INTO Medicines ({columns}) VALUES ({values})"

    conn = await get_db_connection()
    cursor = conn.cursor()
    cursor.execute(query, tuple(new_medicine.values()))
    conn.commit()
    cursor.close()
    conn.close()

    await update.message.reply_text("Лекарство успешно добавлено!")
    return ConversationHandler.END

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "back":
        if context.user_data["current_attr"] > 0:
            context.user_data["current_attr"] -= 1  # Назад на шаг
            return await ask_next_attribute(update, context)
    elif query.data == "cancel":
        await query.message.reply_text("Добавление лекарства отменено.")
        return ConversationHandler.END

async def receive_medicine_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get(SEARCHING_MEDICINE):
        return
    
    context.user_data[SEARCHING_MEDICINE] = False
    name_part = update.message.text
    results = await search_medicine_by_name(name_part)
    
    if not results:
        await update.message.reply_text("Лекарство не найдено.")
        return
    
    keyboard = [[InlineKeyboardButton(name, callback_data=f"select_{name}")] for name in results]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выберите лекарство:", reply_markup=reply_markup)

async def select_medicine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    name = query.data.replace("select_", "")
    details = await get_medicine_details(name)
    
    if not details:
        await query.edit_message_text("Ошибка получения данных.")
        return
    
    context.user_data['selected_medicine'] = details.Name
    
    keyboard = [
        [InlineKeyboardButton("Состав", callback_data="attr_Composition")],
        [InlineKeyboardButton("Показания", callback_data="attr_Indications")],
        [InlineKeyboardButton("Противопоказания", callback_data="attr_Contraindications")],
        [InlineKeyboardButton("Побочные эффекты", callback_data="attr_SideEffects")],
        [InlineKeyboardButton("Рекомендации по дозировке", callback_data="attr_Dosage")],
        [InlineKeyboardButton("Передозировка", callback_data="attr_Overdose")],
        [InlineKeyboardButton("Применение при беременности", callback_data="attr_PregnancyAndLactation")],
        [InlineKeyboardButton("Особые указания", callback_data="attr_SpecialInstructions")],
        [InlineKeyboardButton("Взаимодействие с другими лекарствами", callback_data="attr_DrugInteractions")],
        [InlineKeyboardButton("Бюджетные аналоги", callback_data="attr_BudgetAlternatives")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = f"*Название:* {escape_markdown(details.Name, version=2)}\n"
    text += f"*Международное название:* {escape_markdown(details.InternationalName or 'Не указано', version=2)}\n"
    text += f"*Код АТХ:* {escape_markdown(details.ATCCode or 'Не указано', version=2)}\n"
    text += f"*Лекарственная форма:* {escape_markdown(details.DosageForm or 'Не указано', version=2)}"
    
    await query.edit_message_text(text, parse_mode='MarkdownV2', reply_markup=reply_markup)

async def show_attribute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    attr = query.data.replace("attr_", "")
    attr_names = {
        "Composition": "Состав",
        "Indications": "Показания",
        "Contraindications": "Противопоказания",
        "SideEffects": "Побочные эффекты",
        "Dosage": "Рекомендации по дозировке",
        "Overdose": "Передозировка",
        "PregnancyAndLactation": "Применение при беременности",
        "SpecialInstructions": "Особые указания",
        "DrugInteractions": "Взаимодействие с другими лекарствами",
        "BudgetAlternatives": "Бюджетные аналоги"
    }
    
    name = context.user_data.get('selected_medicine')
    details = await get_medicine_details(name)
    
    if not details:
        await query.edit_message_text("Ошибка получения данных.")
        return
    
    text = f"*{attr_names.get(attr, attr)}:* {escape_markdown(getattr(details, attr, 'Нет данных'), version=2)}"
    keyboard = [[InlineKeyboardButton("Назад", callback_data="select_" + name)]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, parse_mode='MarkdownV2', reply_markup=reply_markup)

if __name__ == '__main__':
    application = ApplicationBuilder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Text("🔍 Поиск лекарства"), request_medicine_name))
    application.add_handler(CallbackQueryHandler(button_callback, pattern="^(back|cancel)$"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_medicine_name))
    application.add_handler(CallbackQueryHandler(select_medicine, pattern="^select_"))
    application.add_handler(CallbackQueryHandler(show_attribute, pattern="^attr_"))
    application.run_polling()
