import telebot
import os
import webbrowser
from telebot import types
bot = telebot.TeleBot(os.getenv('TOKEN'))

#skuf

@bot.message_handler(func=lambda message: message.text == 'мой репозиторий на Github ')
def diary(message):
    bot.send_message(message.chat.id, 'https://github.com/Lapuxovskiy/tg-bot')


    
@bot.message_handler(commands=['start'])      #создаем кнопки при команде старт
def start(message):
    markup = types.ReplyKeyboardMarkup()
    btn1 = types.KeyboardButton('Github')
    markup.row(btn1)
    btn2 = types.KeyboardButton('удалить фото')
    btn3 = types.KeyboardButton('изменить текст')
    markup.row(btn2, btn3)
    bot.send_message(message.chat.id, 'Привет', reply_markup=markup)




@bot.message_handler(func=lambda m: m.text in ['Github', 'удалить фото', 'изменить текст'])
def on_click(message):
    if message.text.lower() == 'github':
        bot.send_message(message.chat.id, 'https://github.com/Lapuxovskiy/tg-bot')
    elif message.text.lower() == 'удалить фото':
        bot.send_message(message.chat.id, 'the photo was deleted')
    elif message.text == 'изменить текст':
        bot.send_message(message.chat.id, 'введи новый текст')












@bot.message_handler(content_types=['photo'])
def get_photo(message):
    markup = types.InlineKeyboardMarkup()
    btn1 = types.InlineKeyboardButton('мой репозиторий на Github ', url='https://github.com/Lapuxovskiy/tg-bot')
    markup.row(btn1)

    btn2 = types.InlineKeyboardButton('удалить фото', callback_data='delete')
    btn3 = types.InlineKeyboardButton('изменить текст', callback_data='edit')
    markup.row(btn2, btn3)

    bot.reply_to(message, 'красивое фото', reply_markup=markup)


@bot.callback_query_handler(func=lambda callback: True)
def callback_message(callback):
    if callback.data == 'delete':
        bot.delete_message(callback.message.chat.id, callback.message.message_id -1)
    elif callback.data == 'edit':
        bot.edit_message_text('Edit text', callback.message.chat.id, callback.message.message_id )






#@bot.message_handler(commands=['start', 'main', 'hello'])
#def main(message):
    #bot.send_message(message.chat.id, f'привет, {message.from_user.first_name} {message.from_user.last_name}')

@bot.message_handler()
def info(message):
    if message.text.lower() == 'привет':
        bot.send_message(message.chat.id, f'привет, {message.from_user.first_name} {message.from_user.last_name}')
    elif message.text.lower() == 'id':
        bot.reply_to(message, f'ID: {message.from_user.id}')
    elif message.text.lower() == 'создатель':
            bot.send_message(message.chat.id, f'бот был создан @Iapuxovskiy')


                     
bot.polling(non_stop = True)

