import os, json, hashlib, hmac, time, uuid, re, base64 as b64mod
from datetime import datetime
from urllib.parse import unquote
from flask import Flask, request, jsonify, send_from_directory
import psycopg2, psycopg2.extras
import requests as req
import yaml as pyyaml

app = Flask(__name__, static_folder='static')
VERSION = '4.10.0'
BOTBUILDER_TOKEN = os.environ.get('BOTBUILDER_TOKEN', '')
DATABASE_URL = os.environ.get('DATABASE_URL', '')
RAILWAY_URL = os.environ.get('RAILWAY_URL', '')

SUPPORTED_ON_INPUT = {
    'call_ai', 'call_openai', 'call_anthropic',
    'call_ai_vision', 'call_openai_vision', 'call_anthropic_vision',
    'reply', 'show_menu', 'next_flow', 'inline_buttons',
    'vision_prompt', 'loading_text'
}

TEMPLATES = [
    {
        'id': 'ai_chat', 'name': 'AI Chat Assistant', 'emoji': chr(0x1f916),
        'description': 'General AI assistant that answers any questions',
        'requires': 'ai_key',
        'yaml': """bot:
  name: AI Assistant
  platform: telegram
  welcome: "\U0001f44b Hello! I am your AI assistant. Ask me anything!"
  default_reply: Type a question or use the menu.
  menu:
    - text: "\U0001f4ac Ask AI"
      flow: ask_ai
    - text: "\U0001f504 New Topic"
      flow: new_topic
    - text: "\u2753 Help"
      flow: help
  flows:
    ask_ai:
      ask: What would you like to know?
      on_input:
        call_ai:
          system: You are a helpful and friendly AI assistant. Give clear, concise answers.
          prompt: "{{input}}"
        reply: "{{ai_result}}"
        show_menu: true
    new_topic:
      reply: "\U0001f504 Ready for a new topic! What would you like to know?"
      show_menu: true
    help:
      reply: "\U0001f4a1 Just type any question and I will answer using AI!"
      show_menu: true"""
    },
    {
        'id': 'translator', 'name': 'Translator Bot', 'emoji': chr(0x1f30f),
        'description': 'Translate text and photos from any language to Russian',
        'requires': 'ai_key',
        'yaml': """bot:
  name: Translator
  platform: telegram
  welcome: "\U0001f30f Welcome! I can translate text and photos to Russian."
  default_reply: Use the menu to start translating.
  menu:
    - text: "\u270d\ufe0f Translate Text"
      flow: translate_text
    - text: "\U0001f4f7 Translate Photo"
      flow: translate_photo
    - text: "\u2753 Help"
      flow: help
  flows:
    translate_text:
      ask: "\u270d\ufe0f Send text to translate:"
      on_input:
        call_ai:
          system: You are a professional translator. Translate the given text to Russian. Return ONLY the translation, no explanations.
          prompt: "{{input}}"
        reply: "\U0001f1f7\U0001f1fa Translation:\n{{ai_result}}"
        show_menu: true
    translate_photo:
      ask: "\U0001f4f7 Send a photo with text to translate:"
      on_input:
        call_ai_vision:
          prompt: Extract ALL text from this image. Then translate it to Russian. Format your answer as: ORIGINAL TEXT:\n[original]\n\nRUSSIAN TRANSLATION:\n[translation]
        reply: "{{ai_result}}"
        show_menu: true
    help:
      reply: "\U0001f4a1 Use menu buttons to translate text or photos. Supports any language!"
      show_menu: true"""
    },
    {
        'id': 'faq', 'name': 'FAQ / Info Bot', 'emoji': chr(0x1f4cb),
        'description': 'Information bot with FAQ, contacts and working hours. No API needed.',
        'requires': 'none',
        'yaml': """bot:
  name: FAQ Bot
  platform: telegram
  welcome: "\U0001f44b Welcome! How can I help you?"
  default_reply: Please use the menu to find information.
  menu:
    - text: "\u2139\ufe0f About Us"
      flow: about
    - text: "\U0001f4bc Services"
      flow: services
    - text: "\u23f0 Working Hours"
      flow: hours
    - text: "\U0001f4de Contacts"
      flow: contacts
  flows:
    about:
      reply: "\u2139\ufe0f We are a company that provides quality services.\n\nEdit this text in the Mini App after creating the bot."
      show_menu: true
    services:
      reply: "\U0001f4bc Our services:\n\n\u2022 Service 1\n\u2022 Service 2\n\u2022 Service 3\n\nContact us for details!"
      show_menu: true
    hours:
      reply: "\u23f0 Working hours:\nMon-Fri: 9:00 - 18:00\nSat: 10:00 - 15:00\nSun: Closed"
      show_menu: true
    contacts:
      reply: "\U0001f4de Contact us:\n\U0001f4f1 Phone: +7 (xxx) xxx-xx-xx\n\U0001f4e7 Email: info@example.com\n\U0001f4cd Address: Your address here"
      show_menu: true"""
    },
    {
        'id': 'support', 'name': 'Customer Support', 'emoji': chr(0x1f91d),
        'description': 'Collect feedback, questions and support requests. No API needed.',
        'requires': 'none',
        'yaml': """bot:
  name: Support Bot
  platform: telegram
  welcome: "\U0001f91d Hello! We are here to help. Choose an option:"
  default_reply: Please use the menu below.
  menu:
    - text: "\u2b50 Leave Feedback"
      flow: feedback
    - text: "\u2753 Ask a Question"
      flow: ask_question
    - text: "\U0001f6a8 Report a Problem"
      flow: report
    - text: "\U0001f4de Contacts"
      flow: contacts
  flows:
    feedback:
      ask: "\u2b50 Please share your feedback:"
      on_input:
        reply: "\u2705 Thank you for your feedback! We appreciate it and will review your message."
        show_menu: true
    ask_question:
      ask: "\u2753 What is your question?"
      on_input:
        reply: "\U0001f4e8 Your question has been received! We will respond within 24 hours."
        show_menu: true
    report:
      ask: "\U0001f6a8 Please describe the problem:"
      on_input:
        reply: "\u2705 Problem reported! Our team will look into it as soon as possible."
        show_menu: true
    contacts:
      reply: "\U0001f4de Reach us directly:\n@your_username\ninfo@example.com"
      show_menu: true"""
    },
    {
        'id': 'vision', 'name': 'Photo Analyzer', 'emoji': chr(0x1f4f8),
        'description': 'Analyze photos, extract text, identify objects using AI vision.',
        'requires': 'ai_key',
        'yaml': """bot:
  name: Photo Analyzer
  platform: telegram
  welcome: "\U0001f4f8 Send me a photo and I will analyze it!"
  default_reply: Send a photo or choose what to do with it from the menu.
  photo_flow: auto_analyze
  menu:
    - text: "\U0001f50d Analyze Photo"
      flow: analyze_prompt
    - text: "\U0001f4dd Extract Text"
      flow: extract_text
    - text: "\U0001f50e Identify Object"
      flow: identify
  flows:
    auto_analyze:
      handle_photo: true
      call_ai_vision:
        prompt: Describe this image in detail. What do you see? If there is any text, extract it.
      reply: "\U0001f50d Analysis:\n{{ai_result}}"
    analyze_prompt:
      ask: "\U0001f50d Send a photo to analyze:"
      on_input:
        call_ai_vision:
          prompt: Describe this image in detail. What objects, people, text or scenes do you see?
        reply: "\U0001f50d Result:\n{{ai_result}}"
        show_menu: true
    extract_text:
      ask: "\U0001f4dd Send a photo to extract text from:"
      on_input:
        call_ai_vision:
          prompt: Extract ALL text visible in this image. Return only the text, preserving its structure.
        reply: "\U0001f4dd Extracted text:\n{{ai_result}}"
        show_menu: true
    identify:
      ask: "\U0001f50e Send a photo to identify the object:"
      on_input:
        call_ai_vision:
          prompt: What is the main object or subject in this photo? Identify it precisely with details.
        reply: "\U0001f50e Identified:\n{{ai_result}}"
        show_menu: true"""
    },
    {
        'id': 'catalog', 'name': 'Product Catalog', 'emoji': chr(0x1f6cd),
        'description': 'Present products/services, prices and ordering info. No API needed.',
        'requires': 'none',
        'yaml': """bot:
  name: Shop Bot
  platform: telegram
  welcome: "\U0001f6cd Welcome to our shop! Browse our catalog:"
  default_reply: Use the menu to explore our catalog.
  menu:
    - text: "\U0001f4e6 Products"
      flow: products
    - text: "\U0001f4b0 Pricing"
      flow: pricing
    - text: "\U0001f69a Delivery"
      flow: delivery
    - text: "\U0001f6d2 How to Order"
      flow: order
    - text: "\U0001f4de Contacts"
      flow: contacts
  flows:
    products:
      reply: "\U0001f4e6 Our products:\n\n1. Product Name - Description\n2. Product Name - Description\n3. Product Name - Description\n\nEdit this list after creating the bot."
      show_menu: true
    pricing:
      reply: "\U0001f4b0 Prices:\n\n\u2022 Basic: $X\n\u2022 Standard: $Y\n\u2022 Premium: $Z\n\nAll prices include VAT."
      show_menu: true
    delivery:
      reply: "\U0001f69a Delivery info:\n\u2022 Standard: 3-5 days\n\u2022 Express: 1-2 days\n\u2022 Free shipping on orders over $50"
      show_menu: true
    order:
      ask: "\U0001f6d2 Tell us what you want to order:"
      on_input:
        reply: "\u2705 Order received! We will contact you within 1 hour to confirm."
        show_menu: true
    contacts:
      reply: "\U0001f4de Contact us:\n\U0001f4f1 +7 (xxx) xxx-xx-xx\n\U0001f4e7 shop@example.com"
      show_menu: true"""
    },

    {
        'id': 'lead_capture', 'name': 'Lead Capture', 'emoji': '\U0001f3af',
        'description': 'Collect leads: name, company, contact, need. Multi-step funnel. No API needed.',
        'category': 'Marketing',
        'requires': 'none',
        'yaml': (
            'bot:\n'
            '  name: Lead Bot\n'
            '  platform: telegram\n'
            '  welcome: "\U0001f3af Hello! Let me learn about your needs."\n'
            '  default_reply: Use the menu below.\n'
            '  menu:\n'
            '    - text: "\U0001f4cb Start Form"\n'
            '      flow: step_name\n'
            '    - text: "\u2139\ufe0f About Us"\n'
            '      flow: about\n'
            '    - text: "\U0001f4de Contact Manager"\n'
            '      flow: contacts\n'
            '  flows:\n'
            '    step_name:\n'
            '      ask: "\U0001f464 Step 1/4. Your name?"\n'
            '      on_input:\n'
            '        reply: "\u2705 Nice, {{input}}! Step 2/4:"\n'
            '        next_flow: step_company\n'
            '    step_company:\n'
            '      ask: "\U0001f3e2 Step 2/4. Your company?"\n'
            '      on_input:\n'
            '        reply: "\u2705 Got it! Step 3/4:"\n'
            '        next_flow: step_need\n'
            '    step_need:\n'
            '      ask: "\U0001f4a1 Step 3/4. What problem to solve?"\n'
            '      on_input:\n'
            '        reply: "\u2705 Understood! Last step:"\n'
            '        next_flow: step_contact\n'
            '    step_contact:\n'
            '      ask: "\U0001f4f1 Step 4/4. Phone or email:"\n'
            '      on_input:\n'
            '        reply: "\U0001f389 Thank you! Request registered.\\nWe will contact you shortly with a personal offer.\\n\\n\u23f0 Response: within 2 hours."\n'
            '        show_menu: true\n'
            '    about:\n'
            '      reply: "\u2139\ufe0f We help businesses grow. 500+ companies served.\\nSpecialties: consulting, automation, digital transformation."\n'
            '      show_menu: true\n'
            '    contacts:\n'
            '      reply: "\U0001f4de Talk to a manager:\\n\U0001f4f1 +7 (xxx) xxx-xx-xx\\n\U0001f4e7 sales@example.com"\n'
            '      show_menu: true\n'
        )
    },
    {
        'id': 'quiz_trivia', 'name': 'Quiz / Trivia Game', 'emoji': '\U0001f9e0',
        'description': 'Interactive quiz with inline A/B/C buttons and score tracking. No API needed.',
        'category': 'Entertainment',
        'requires': 'none',
        'yaml': (
            'bot:\n'
            '  name: Quiz Bot\n'
            '  platform: telegram\n'
            '  welcome: "\U0001f9e0 Welcome to Quiz! Press Start to begin!"\n'
            '  default_reply: Press Start Quiz to play!\n'
            '  menu:\n'
            '    - text: "\U0001f3ae Start Quiz"\n'
            '      flow: question_1\n'
            '    - text: "\U0001f4dc Rules"\n'
            '      flow: rules\n'
            '  flows:\n'
            '    rules:\n'
            '      reply: "\U0001f4dc Rules:\\n\u2022 5 questions\\n\u2022 Choose A, B or C\\nPress Start Quiz!"\n'
            '      show_menu: true\n'
            '    question_1:\n'
            '      ask: "\U0001f9e0 Q1/5: Capital of France?"\n'
            '      inline_buttons:\n'
            '        - text: "A) London"\n'
            '          flow: q1_wrong\n'
            '        - text: "B) Paris"\n'
            '          flow: q1_correct\n'
            '        - text: "C) Berlin"\n'
            '          flow: q1_wrong\n'
            '    q1_correct:\n'
            '      reply: "\u2705 Correct! Paris. Next:"\n'
            '      next_flow: question_2\n'
            '    q1_wrong:\n'
            '      reply: "\u274c Wrong! B) Paris. Next:"\n'
            '      next_flow: question_2\n'
            '    question_2:\n'
            '      ask: "\U0001f9e0 Q2/5: Planets in Solar System?"\n'
            '      inline_buttons:\n'
            '        - text: "A) 7"\n'
            '          flow: q2_wrong\n'
            '        - text: "B) 8"\n'
            '          flow: q2_correct\n'
            '        - text: "C) 9"\n'
            '          flow: q2_wrong\n'
            '    q2_correct:\n'
            '      reply: "\u2705 Correct! 8 planets. Next:"\n'
            '      next_flow: question_3\n'
            '    q2_wrong:\n'
            '      reply: "\u274c Wrong! B) 8. Next:"\n'
            '      next_flow: question_3\n'
            '    question_3:\n'
            '      ask: "\U0001f9e0 Q3/5: WWII ended in?"\n'
            '      inline_buttons:\n'
            '        - text: "A) 1943"\n'
            '          flow: q3_wrong\n'
            '        - text: "B) 1945"\n'
            '          flow: q3_correct\n'
            '        - text: "C) 1947"\n'
            '          flow: q3_wrong\n'
            '    q3_correct:\n'
            '      reply: "\u2705 Correct! 1945. Next:"\n'
            '      next_flow: question_4\n'
            '    q3_wrong:\n'
            '      reply: "\u274c Wrong! B) 1945. Next:"\n'
            '      next_flow: question_4\n'
            '    question_4:\n'
            '      ask: "\U0001f9e0 Q4/5: H2O is?"\n'
            '      inline_buttons:\n'
            '        - text: "A) Oxygen"\n'
            '          flow: q4_wrong\n'
            '        - text: "B) Hydrogen"\n'
            '          flow: q4_wrong\n'
            '        - text: "C) Water"\n'
            '          flow: q4_correct\n'
            '    q4_correct:\n'
            '      reply: "\u2705 Correct! H2O = Water. Last Q!"\n'
            '      next_flow: question_5\n'
            '    q4_wrong:\n'
            '      reply: "\u274c Wrong! C) Water. Last Q!"\n'
            '      next_flow: question_5\n'
            '    question_5:\n'
            '      ask: "\U0001f9e0 Q5/5: Sides of a hexagon?"\n'
            '      inline_buttons:\n'
            '        - text: "A) 5"\n'
            '          flow: q5_wrong\n'
            '        - text: "B) 6"\n'
            '          flow: q5_correct\n'
            '        - text: "C) 7"\n'
            '          flow: q5_wrong\n'
            '    q5_correct:\n'
            '      reply: "\u2705 Correct! \U0001f3c6 Quiz done! Play again?"\n'
            '      show_menu: true\n'
            '    q5_wrong:\n'
            '      reply: "\u274c Wrong! B) 6 sides. \U0001f3c6 Done! Try again?"\n'
            '      show_menu: true\n'
        )
    },
    {
        'id': 'appointment', 'name': 'Appointment Booking', 'emoji': '\U0001f4c5',
        'description': 'Multi-step booking: service, contact info, time slot. No API needed.',
        'category': 'Business',
        'requires': 'none',
        'yaml': (
            'bot:\n'
            '  name: Booking Bot\n'
            '  platform: telegram\n'
            '  welcome: "\U0001f4c5 Welcome! Book in 3 easy steps."\n'
            '  default_reply: Use menu to book.\n'
            '  menu:\n'
            '    - text: "\U0001f4c5 Book Appointment"\n'
            '      flow: choose_service\n'
            '    - text: "\u23f0 Available Hours"\n'
            '      flow: show_hours\n'
            '    - text: "\U0001f4de Contact Us"\n'
            '      flow: contacts\n'
            '  flows:\n'
            '    choose_service:\n'
            '      ask: "\U0001f4bc Step 1/3. Choose a service:"\n'
            '      inline_buttons:\n'
            '        - text: "\U0001f4c4 Consultation"\n'
            '          flow: ask_contacts\n'
            '        - text: "\U0001f527 Technical Service"\n'
            '          flow: ask_contacts\n'
            '        - text: "\U0001f4b0 Financial Advice"\n'
            '          flow: ask_contacts\n'
            '    ask_contacts:\n'
            '      ask: "\u2705 Service selected!\\n\\nStep 2/3. Your name and phone:"\n'
            '      on_input:\n'
            '        reply: "\u2705 Contact saved! Step 3/3:"\n'
            '        next_flow: choose_time\n'
            '    choose_time:\n'
            '      ask: "\u23f0 Step 3/3. Choose time:"\n'
            '      inline_buttons:\n'
            '        - text: "10:00 Morning"\n'
            '          flow: confirm_morning\n'
            '        - text: "14:00 Afternoon"\n'
            '          flow: confirm_afternoon\n'
            '        - text: "18:00 Evening"\n'
            '          flow: confirm_evening\n'
            '    confirm_morning:\n'
            '      reply: "\U0001f389 Confirmed for 10:00!\\n\U0001f4cb We will call to confirm.\\nSee you soon! \U0001f44b"\n'
            '      show_menu: true\n'
            '    confirm_afternoon:\n'
            '      reply: "\U0001f389 Confirmed for 14:00!\\n\U0001f4cb We will call to confirm.\\nSee you soon! \U0001f44b"\n'
            '      show_menu: true\n'
            '    confirm_evening:\n'
            '      reply: "\U0001f389 Confirmed for 18:00!\\n\U0001f4cb We will call to confirm.\\nSee you soon! \U0001f44b"\n'
            '      show_menu: true\n'
            '    show_hours:\n'
            '      reply: "\u23f0 Available slots:\\nMon-Fri: 10:00, 14:00, 18:00\\nSat: 10:00-13:00\\nSun: Closed"\n'
            '      show_menu: true\n'
            '    contacts:\n'
            '      reply: "\U0001f4de +7 (xxx) xxx-xx-xx\\nbooking@example.com"\n'
            '      show_menu: true\n'
        )
    },
    {
        'id': 'recipe_ai', 'name': 'Recipe Assistant', 'emoji': '\U0001f373',
        'description': 'AI generates recipes from ingredients text or food photos.',
        'category': 'AI',
        'requires': 'ai_key',
        'yaml': (
            'bot:\n'
            '  name: Recipe Bot\n'
            '  platform: telegram\n'
            '  welcome: "\U0001f373 Hello Chef! Send ingredients or a food photo!"\n'
            '  default_reply: Tell me your ingredients or send a food photo!\n'
            '  photo_flow: analyze_food_photo\n'
            '  menu:\n'
            '    - text: "\U0001f355 Get Recipe"\n'
            '      flow: get_recipe\n'
            '    - text: "\U0001f4f7 Analyze Food Photo"\n'
            '      flow: request_photo\n'
            '    - text: "\U0001f331 Vegetarian"\n'
            '      flow: vegetarian\n'
            '    - text: "\U0001f96a Meal Suggestion"\n'
            '      flow: suggest_meal\n'
            '  flows:\n'
            '    get_recipe:\n'
            '      ask: "\U0001f4dd List your ingredients:"\n'
            '      on_input:\n'
            '        call_ai:\n'
            '          system: "You are a professional chef. Create a complete recipe from the ingredients. Include: dish name, prep time, step-by-step instructions."\n'
            '          prompt: "Ingredients: {{input}}. What to cook?"\n'
            '        reply: "\U0001f373 Recipe:\\n\\n{{ai_result}}"\n'
            '        show_menu: true\n'
            '    request_photo:\n'
            '      ask: "\U0001f4f7 Send a photo of your ingredients:"\n'
            '      on_input:\n'
            '        call_ai_vision:\n'
            '          prompt: "Identify food ingredients in this photo. Suggest 2 recipes using them with basic steps."\n'
            '        reply: "\U0001f50d Photo analyzed!\\n\\n{{ai_result}}"\n'
            '        show_menu: true\n'
            '    analyze_food_photo:\n'
            '      handle_photo: true\n'
            '      call_ai_vision:\n'
            '        prompt: "Identify this dish, describe it, estimate calories, suggest how to improve serving."\n'
            '      reply: "\U0001f374 Food analysis:\\n\\n{{ai_result}}"\n'
            '    vegetarian:\n'
            '      ask: "\U0001f331 What vegetables do you have?"\n'
            '      on_input:\n'
            '        call_ai:\n'
            '          system: "You are a vegetarian cuisine expert. Create a delicious vegetarian recipe. No meat."\n'
            '          prompt: "Vegetarian recipe with: {{input}}"\n'
            '        reply: "\U0001f331 Vegetarian recipe:\\n\\n{{ai_result}}"\n'
            '        show_menu: true\n'
            '    suggest_meal:\n'
            '      ask: "\U0001f96a Mood or cuisine? (Italian, healthy, quick...):"\n'
            '      on_input:\n'
            '        call_ai:\n'
            '          system: "You are a food expert. Suggest a perfect meal based on mood/cuisine preference."\n'
            '          prompt: "Meal suggestion for: {{input}}"\n'
            '        reply: "\U0001f371 My suggestion:\\n\\n{{ai_result}}"\n'
            '        show_menu: true\n'
        )
    },
    {
        'id': 'language_tutor', 'name': 'Language Tutor', 'emoji': '\U0001f4d6',
        'description': 'AI language learning: exercises, translations, grammar correction.',
        'category': 'Education',
        'requires': 'ai_key',
        'yaml': (
            'bot:\n'
            '  name: Language Tutor\n'
            '  platform: telegram\n'
            '  welcome: "\U0001f4d6 Welcome! I will help you learn languages."\n'
            '  default_reply: Use the menu to practice.\n'
            '  menu:\n'
            '    - text: "\U0001f1ec\U0001f1e7 English Check"\n'
            '      flow: english_practice\n'
            '    - text: "\u270d\ufe0f Grammar Check"\n'
            '      flow: grammar_check\n'
            '    - text: "\U0001f4ac Translate & Explain"\n'
            '      flow: translate_explain\n'
            '    - text: "\U0001f9e9 Daily Phrase"\n'
            '      flow: daily_phrase\n'
            '  flows:\n'
            '    english_practice:\n'
            '      ask: "\U0001f1ec\U0001f1e7 Write a sentence in English to check:"\n'
            '      on_input:\n'
            '        call_ai:\n'
            '          system: "You are an English teacher. Check the text: 1) Correct grammar errors 2) Explain corrections 3) Give improved version 4) Vocabulary tip."\n'
            '          prompt: "Check my English: {{input}}"\n'
            '        reply: "\U0001f4dd Feedback:\\n\\n{{ai_result}}"\n'
            '        show_menu: true\n'
            '    grammar_check:\n'
            '      ask: "\u270d\ufe0f Text for grammar check:"\n'
            '      on_input:\n'
            '        call_ai:\n'
            '          system: "Check grammar of this text. List errors with explanations. Provide corrected version."\n'
            '          prompt: "Grammar check: {{input}}"\n'
            '        reply: "\u270f\ufe0f Grammar:\\n\\n{{ai_result}}"\n'
            '        show_menu: true\n'
            '    translate_explain:\n'
            '      ask: "\U0001f4ac Word or phrase to translate:"\n'
            '      on_input:\n'
            '        call_ai:\n'
            '          system: "Translate to Russian, give 3 example sentences, explain idioms."\n'
            '          prompt: "Translate and explain: {{input}}"\n'
            '        reply: "\U0001f4da Explanation:\\n\\n{{ai_result}}"\n'
            '        show_menu: true\n'
            '    daily_phrase:\n'
            '      ask: "\U0001f9e9 Which language? (English, Spanish, French...):"\n'
            '      on_input:\n'
            '        call_ai:\n'
            '          system: "Generate a useful daily phrase in the requested language with pronunciation and Russian translation."\n'
            '          prompt: "Daily phrase in: {{input}}"\n'
            '        reply: "\U0001f4ab Today phrase:\\n\\n{{ai_result}}"\n'
            '        show_menu: true\n'
        )
    },
    {
        'id': 'personal_coach', 'name': 'Personal Fitness Coach', 'emoji': '\U0001f3cb',
        'description': 'AI fitness coach: workout plans, nutrition advice, form check from photos.',
        'category': 'Health',
        'requires': 'ai_key',
        'yaml': (
            'bot:\n'
            '  name: Fitness Coach\n'
            '  platform: telegram\n'
            '  welcome: "\U0001f3cb\ufe0f Hello! I am your personal AI fitness coach."\n'
            '  default_reply: Use menu or send exercise photo.\n'
            '  photo_flow: check_form\n'
            '  menu:\n'
            '    - text: "\U0001f4aa Workout Plan"\n'
            '      flow: workout_plan\n'
            '    - text: "\U0001f955 Nutrition"\n'
            '      flow: nutrition\n'
            '    - text: "\U0001f4f7 Check My Form"\n'
            '      flow: form_check_prompt\n'
            '    - text: "\U0001f525 Motivate Me"\n'
            '      flow: motivation\n'
            '  flows:\n'
            '    workout_plan:\n'
            '      ask: "\U0001f4aa Fitness level (beginner/intermediate/advanced), goal, equipment:"\n'
            '      on_input:\n'
            '        call_ai:\n'
            '          system: "You are a certified personal trainer. Create a personalized weekly workout with sets/reps, warm-up and cool-down."\n'
            '          prompt: "Create workout plan for: {{input}}"\n'
            '        reply: "\U0001f4aa Workout plan:\\n\\n{{ai_result}}"\n'
            '        show_menu: true\n'
            '    nutrition:\n'
            '      ask: "\U0001f955 Your goal + dietary restrictions:"\n'
            '      on_input:\n'
            '        call_ai:\n'
            '          system: "You are a certified nutritionist. Give practical advice with macros, meal timing, top foods to eat and avoid."\n'
            '          prompt: "Nutrition advice for: {{input}}"\n'
            '        reply: "\U0001f957 Nutrition plan:\\n\\n{{ai_result}}"\n'
            '        show_menu: true\n'
            '    form_check_prompt:\n'
            '      ask: "\U0001f4f7 Send exercise photo to check form:"\n'
            '      on_input:\n'
            '        call_ai_vision:\n'
            '          prompt: "Analyze exercise form: 1) Identify exercise 2) Rate technique 3) Correct issues for safety."\n'
            '        reply: "\U0001f4cb Form analysis:\\n\\n{{ai_result}}"\n'
            '        show_menu: true\n'
            '    check_form:\n'
            '      handle_photo: true\n'
            '      call_ai_vision:\n'
            '        prompt: "Analyze exercise form. Rate it, list what is correct, identify issues and corrections."\n'
            '      reply: "\U0001f4cb Form check:\\n\\n{{ai_result}}"\n'
            '    motivation:\n'
            '      ask: "\U0001f525 How are you feeling? (tired/unmotivated/stressed/ready):"\n'
            '      on_input:\n'
            '        call_ai:\n'
            '          system: "You are an energetic coach. Give powerful personalized motivation with quote and one action to take now."\n'
            '          prompt: "Motivate me, I feel: {{input}}"\n'
            '        reply: "\U0001f525 {{ai_result}}"\n'
            '        show_menu: true\n'
        )
    },

]


def get_db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def init_db():
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS users (
                telegram_id BIGINT PRIMARY KEY, username TEXT DEFAULT '',
                first_name TEXT DEFAULT '', created_at TIMESTAMPTZ DEFAULT NOW())""")
            cur.execute("""CREATE TABLE IF NOT EXISTS bots (
                id TEXT PRIMARY KEY, user_id BIGINT REFERENCES users(telegram_id),
                name TEXT NOT NULL, description TEXT DEFAULT '',
                yaml_definition TEXT DEFAULT '', bot_token TEXT, bot_token_hash TEXT UNIQUE,
                bot_username TEXT DEFAULT '', ai_api_key TEXT DEFAULT '',
                ai_provider TEXT DEFAULT 'anthropic', yaml_backup TEXT DEFAULT '', status TEXT DEFAULT 'inactive',
                created_at TIMESTAMPTZ DEFAULT NOW(), updated_at TIMESTAMPTZ DEFAULT NOW())""")
            for col, defn in [
                ('bot_username', "TEXT DEFAULT ''"),
                ('ai_api_key', "TEXT DEFAULT ''"),
                ('ai_provider', "TEXT DEFAULT 'anthropic'")
            ]:
                try:
                    cur.execute(f'ALTER TABLE bots ADD COLUMN IF NOT EXISTS {col} {defn}')
                except Exception:
                    pass
            cur.execute("""CREATE TABLE IF NOT EXISTS bot_states (
                bot_id TEXT, chat_id TEXT, state_key TEXT, state_value TEXT,
                updated_at TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (bot_id, chat_id, state_key))""")
        conn.commit()
        print(f'[OK] DB v{VERSION} ready')
    except Exception as e:
        print(f'[DB] {e}'); conn.rollback()
    finally:
        conn.close()


def _sanitize_yaml(yaml_str):
    """Remove unsupported DSL directives. Returns (clean_yaml, warnings)."""
    UNSUPPORTED = {'call_api', 'db_insert', 'db_query', 'db_update',
                   'send_photo', 'reply_after',
                   'if_empty_reply', 'schedule', 'conditions'}
    warnings = []
    try:
        cfg = pyyaml.safe_load(yaml_str)
        if not cfg:
            return yaml_str, ['Empty YAML']
        bc = cfg.get('bot', cfg)
        flows = bc.get('flows', {})
        for fkey, flow in flows.items():
            if not isinstance(flow, dict):
                continue
            oi = flow.get('on_input', {})
            if isinstance(oi, dict):
                removed = [k for k in list(oi.keys()) if k in UNSUPPORTED]
                for k in removed:
                    del oi[k]
                if removed:
                    warnings.append(f"Flow '{fkey}': removed unsupported: {', '.join(removed)}")
                for field in ['reply']:
                    v = str(oi.get(field, ''))
                    v2 = re.sub(r'\{\{recall:[\w.]+\}\}', '[data]', v)
                    if v2 != v:
                        oi[field] = v2
                        warnings.append(f"Flow '{fkey}': replaced unsupported recall vars")
                if oi is not None and len(oi) == 0:
                    if flow.get('inline_buttons'):
                        # Flow has inline_buttons at top level — just delete empty on_input
                        flow.pop('on_input', None)
                    elif flow.get('reply'):
                        # Flow has top-level reply — delete empty on_input
                        flow.pop('on_input', None)
                    elif flow.get('ask') or removed:
                        flow['on_input'] = {
                            'reply': chr(0x2705) + ' Got it! You said: {{input}}',
                            'show_menu': True
                        }
                        warnings.append(f"Flow '{fkey}': added fallback reply (on_input was empty)")
                    else:
                        flow.pop('on_input', None)
                    if removed:
                        warnings.append(f"Flow '{fkey}': removed unsupported ops ({', '.join(removed)})")
            for field in ['reply']:
                v = str(flow.get(field, ''))
                v2 = re.sub(r'\{\{recall:[\w.]+\}\}', '[data]', v)
                if v2 != v:
                    flow[field] = v2
        clean = pyyaml.dump(cfg, allow_unicode=True, default_flow_style=False, indent=2)
        return clean, warnings
    except Exception as e:
        return yaml_str, [f'Sanitize failed: {e}']


def validate_init_data(init_data):
    if not init_data or not BOTBUILDER_TOKEN:
        return None
    try:
        parsed = {}
        for part in init_data.split('&'):
            if '=' in part:
                k, v = part.split('=', 1)
                parsed[k] = unquote(v)
        hash_val = parsed.pop('hash', '')
        data_check = '\n'.join(f'{k}={v}' for k, v in sorted(parsed.items()))
        secret = hmac.new(b'WebAppData', BOTBUILDER_TOKEN.encode(), hashlib.sha256).digest()
        computed = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
        if computed != hash_val or time.time() - int(parsed.get('auth_date', 0)) > 86400:
            return None
        return json.loads(parsed.get('user', '{}'))
    except Exception:
        return None


@app.route('/')
@app.route('/app')
def serve_app():
    return send_from_directory('static', 'index.html')


@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'version': VERSION})


@app.route('/api/templates', methods=['GET'])
def get_templates():
    return jsonify({'ok': True, 'templates': [
        {k: v for k, v in t.items() if k != 'yaml'} for t in TEMPLATES
    ]})


@app.route('/api/template/<tmpl_id>', methods=['GET'])
def get_template(tmpl_id):
    for t in TEMPLATES:
        if t['id'] == tmpl_id:
            return jsonify({'ok': True, 'template': t})
    return jsonify({'error': 'Template not found'}), 404


@app.route('/api/validate_yaml', methods=['POST'])
def validate_yaml_ep():
    data = request.json or {}
    yaml_str = data.get('yaml', '')
    clean, warnings = _sanitize_yaml(yaml_str)
    return jsonify({'ok': True, 'yaml': clean, 'warnings': warnings})


@app.route('/api/auth', methods=['POST'])
def auth():
    data = request.json or {}
    user_data = validate_init_data(data.get('initData', ''))
    if not user_data:
        if os.environ.get('DEV_MODE') == '1':
            user_data = {'id': 12345, 'first_name': 'Dev', 'username': 'dev'}
        else:
            return jsonify({'error': 'Unauthorized'}), 401
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO users (telegram_id, username, first_name)
                VALUES (%s,%s,%s) ON CONFLICT (telegram_id) DO UPDATE
                SET username=EXCLUDED.username, first_name=EXCLUDED.first_name
                RETURNING telegram_id, username, first_name""",
                (user_data['id'], user_data.get('username', ''), user_data.get('first_name', '')))
            user = dict(cur.fetchone())
        conn.commit()
    finally:
        conn.close()
    return jsonify({'ok': True, 'user': user})


@app.route('/api/bots', methods=['GET'])
def list_bots():
    uid = request.args.get('user_id')
    if not uid:
        return jsonify({'error': 'user_id required'}), 400
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT id, user_id, name, description, status, bot_username,
                ai_provider, (ai_api_key != '' AND ai_api_key IS NOT NULL) as has_ai_key,
                created_at FROM bots WHERE user_id=%s ORDER BY created_at DESC""", (uid,))
            bots = [{**dict(r), 'created_at': str(r['created_at'])} for r in cur.fetchall()]
    finally:
        conn.close()
    return jsonify({'bots': bots})


@app.route('/api/bots', methods=['POST'])
def create_bot():
    data = request.json or {}
    uid = data.get('user_id'); bt = data.get('bot_token', '')
    if not uid or not bt:
        return jsonify({'error': 'user_id and bot_token required'}), 400
    try:
        r = req.get(f'https://api.telegram.org/bot{bt}/getMe', timeout=10)
        if not r.ok or not r.json().get('ok'):
            return jsonify({'error': 'Invalid bot token'}), 400
        info = r.json()['result']
    except Exception as e:
        return jsonify({'error': str(e)}), 400
    name = data.get('name') or info.get('first_name', 'My Bot')
    yaml_def = data.get('yaml_definition', '')
    if yaml_def:
        yaml_def, _ = _sanitize_yaml(yaml_def)
    th = hashlib.sha256(bt.encode()).hexdigest()[:32]
    bid = str(uuid.uuid4())
    conn = get_db()
    try:
        with conn.cursor() as cur:
            # Atomic UPSERT — no race condition possible
            new_ai_key = data.get('ai_api_key', '') or ''
            cur.execute(
                """INSERT INTO bots
                    (id, user_id, name, description, yaml_definition,
                     bot_token, bot_token_hash, bot_username,
                     ai_api_key, ai_provider, status)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'inactive')
                   ON CONFLICT (bot_token_hash) DO UPDATE SET
                     name            = EXCLUDED.name,
                     description     = EXCLUDED.description,
                     yaml_definition = EXCLUDED.yaml_definition,
                     bot_username    = EXCLUDED.bot_username,
                     ai_api_key      = CASE WHEN EXCLUDED.ai_api_key != ''
                                            THEN EXCLUDED.ai_api_key
                                            ELSE bots.ai_api_key END,
                     ai_provider     = EXCLUDED.ai_provider,
                     status          = 'inactive',
                     updated_at      = NOW()
                   RETURNING id, user_id, name, description, status, bot_username, created_at""",
                (bid, uid, name, data.get('description', ''), yaml_def, bt, th,
                 info.get('username', ''), new_ai_key,
                 data.get('ai_provider', 'anthropic')))
            bot = dict(cur.fetchone())
            bot['created_at'] = str(bot.get('created_at', ''))
        conn.commit()
    except Exception as e:
        conn.rollback(); conn.close()
        return jsonify({'error': str(e)}), 500
    finally:
        try: conn.close()
        except: pass
    return jsonify({'ok': True, 'bot': bot, 'bot_id': bid})


@app.route('/api/bots/<bot_id>/ai_key', methods=['PUT'])
def update_ai_key(bot_id):
    data = request.json or {}
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute('UPDATE bots SET ai_api_key=%s, ai_provider=%s, updated_at=NOW() WHERE id=%s',
                (data.get('ai_api_key', ''), data.get('ai_provider', 'anthropic'), bot_id))
        conn.commit()
    finally:
        conn.close()
    return jsonify({'ok': True})


@app.route('/api/bots/<bot_id>/yaml', methods=['PUT'])
def update_yaml(bot_id):
    data = request.json or {}
    yaml_def = data.get('yaml_definition', '')
    if yaml_def:
        yaml_def, warnings = _sanitize_yaml(yaml_def)
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute('UPDATE bots SET yaml_definition=%s, updated_at=NOW() WHERE id=%s',
                (yaml_def, bot_id))
        conn.commit()
    finally:
        conn.close()
    return jsonify({'ok': True, 'warnings': warnings if yaml_def else []})


@app.route('/api/bots/<bot_id>/activate', methods=['POST'])
def activate_bot(bot_id):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT * FROM bots WHERE id=%s', (bot_id,))
            bot = cur.fetchone()
    finally:
        conn.close()
    if not bot:
        return jsonify({'error': 'Bot not found'}), 404
    bot = dict(bot)
    if not RAILWAY_URL:
        return jsonify({'error': 'RAILWAY_URL not set'}), 500
    wh = f'{RAILWAY_URL}/bot/{bot["bot_token_hash"]}'
    r = req.post(f'https://api.telegram.org/bot{bot["bot_token"]}/setWebhook',
        json={'url': wh, 'drop_pending_updates': True}, timeout=10)
    if r.ok and r.json().get('ok'):
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE bots SET status='active', updated_at=NOW() WHERE id=%s", (bot_id,))
            conn.commit()
        finally:
            conn.close()
        return jsonify({'ok': True, 'webhook_url': wh})
    return jsonify({'error': 'Webhook failed', 'detail': r.json()}), 500


@app.route('/api/bots/<bot_id>/deactivate', methods=['POST'])
def deactivate_bot(bot_id):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT bot_token FROM bots WHERE id=%s', (bot_id,))
            bot = cur.fetchone()
    finally:
        conn.close()
    if not bot:
        return jsonify({'error': 'Bot not found'}), 404
    try:
        req.post(f'https://api.telegram.org/bot{bot["bot_token"]}/deleteWebhook',
            json={'drop_pending_updates': True}, timeout=10)
    except Exception:
        pass
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE bots SET status='inactive', updated_at=NOW() WHERE id=%s", (bot_id,))
        conn.commit()
    finally:
        conn.close()
    return jsonify({'ok': True})


@app.route('/api/bots/<bot_id>', methods=['DELETE'])
def delete_bot(bot_id):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT bot_token FROM bots WHERE id=%s', (bot_id,))
            bot = cur.fetchone()
            if bot and bot['bot_token']:
                try:
                    req.post(f'https://api.telegram.org/bot{bot["bot_token"]}/deleteWebhook',
                        timeout=5)
                except Exception:
                    pass
            cur.execute('DELETE FROM bot_states WHERE bot_id=%s', (bot_id,))
            cur.execute('DELETE FROM bots WHERE id=%s', (bot_id,))
        conn.commit()
    finally:
        conn.close()
    return jsonify({'ok': True})




def _spec_to_yaml(spec):
    """Deterministic YAML builder from JSON spec. No AI. Always produces valid DSL."""
    FLAGS = {
        'Russian': chr(0x1f1f7)+chr(0x1f1fa), 'English': chr(0x1f1ec)+chr(0x1f1e7),
        'Spanish': chr(0x1f1ea)+chr(0x1f1f8), 'French': chr(0x1f1eb)+chr(0x1f1f7),
        'German': chr(0x1f1e9)+chr(0x1f1ea), 'Chinese': chr(0x1f1e8)+chr(0x1f1f3),
        'Japanese': chr(0x1f1ef)+chr(0x1f1f5), 'Arabic': chr(0x1f1f8)+chr(0x1f1e6),
        'Italian': chr(0x1f1ee)+chr(0x1f1f9), 'Turkish': chr(0x1f1f9)+chr(0x1f1f7),
        'Korean': chr(0x1f1f0)+chr(0x1f1f7), 'Portuguese': chr(0x1f1e7)+chr(0x1f1f7)
    }
    name = spec.get('name', 'My Bot')
    welcome = spec.get('welcome', 'Welcome to ' + name + '!')
    default_reply = spec.get('default_reply', 'Please use the menu.')
    user_vars_d = spec.get('user_vars', {})
    flows_list = spec.get('flows', [])
    menu = []; flows = {}; photo_flow_key = None
    for fs in flows_list:
        key = str(fs.get('key', 'flow'))
        mtext = str(fs.get('menu_text', ''))
        ftype = str(fs.get('type', 'static'))
        if mtext:
            menu.append({'text': mtext, 'flow': key})
        if ftype == 'static':
            flows[key] = {
                'reply': str(fs.get('content', fs.get('reply', chr(0x1f4cc) + ' Info'))),
                'show_menu': True
            }
        elif ftype == 'language_choice':
            langs = [str(l) for l in fs.get('languages', ['Russian','English','Spanish','French','German'])[:6]]
            lang_var = str(fs.get('var', 'lang'))
            buttons = [{'text': FLAGS.get(l, chr(0x1f310)) + ' ' + l,
                        'flow': 'set_lang_' + l.lower().replace(' ', '_')} for l in langs]
            flows[key] = {'ask': chr(0x1f30d) + ' Choose your language:', 'inline_buttons': buttons}
            for lang in langs:
                fk = 'set_lang_' + lang.lower().replace(' ', '_')
                flows[fk] = {
                    'set_vars': {lang_var: lang},
                    'reply': chr(0x2705) + ' Language: ' + FLAGS.get(lang, chr(0x1f310)) + ' ' + lang,
                    'show_menu': True
                }
        elif ftype == 'vision_translate':
            lang_var = str(fs.get('target_lang_var', 'lang'))
            if fs.get('is_photo_flow', True): photo_flow_key = key
            flows[key] = {
                'ask': chr(0x1f4f7) + ' Send a photo with text to translate:',
                'on_input': {
                    'call_ai_vision': {
                        'prompt': (
                            'Extract ALL text from this image. '
                            'Translate it to {{user_var:' + lang_var + '}}. '
                            'Reply in this format:\n'
                            'ORIGINAL TEXT:\n[text from image]\n\n'
                            'TRANSLATION ({{user_var:' + lang_var + '}}):\n[translation]'
                        )
                    },
                    'reply': '{{ai_result}}',
                    'show_menu': True
                }
            }
        elif ftype == 'text_translate':
            lang_var = str(fs.get('target_lang_var', 'lang'))
            flows[key] = {
                'ask': chr(0x270d) + chr(0xfe0f) + ' Enter text to translate:',
                'on_input': {
                    'call_ai': {
                        'system': ('Professional translator. Translate to {{user_var:' + lang_var + '}}. '
                                   'Return ONLY the translation, no extra text.'),
                        'prompt': '{{input}}'
                    },
                    'reply': '{{ai_result}}',
                    'show_menu': True
                }
            }
        elif ftype == 'ai_chat':
            sys_p = str(fs.get('system_prompt', 'You are ' + name + '. Be helpful and friendly.'))
            flows[key] = {
                'ask': str(fs.get('ask', chr(0x1f4ac) + ' Ask me anything:')),
                'on_input': {
                    'call_ai': {'system': sys_p, 'prompt': '{{input}}'},
                    'reply': '{{ai_result}}', 'show_menu': True
                }
            }
        elif ftype == 'collect_input':
            flows[key] = {
                'ask': str(fs.get('ask', chr(0x270f) + ' Enter your message:')),
                'on_input': {
                    'reply': str(fs.get('reply', chr(0x2705) + ' Received!')),
                    'show_menu': True
                }
            }
        elif ftype == 'inline_choice':
            opts = fs.get('options', [])
            buttons = [{'text': str(o.get('text', '?')), 'flow': str(o.get('flow', 'help'))} for o in opts]
            flows[key] = {'ask': str(fs.get('ask', chr(0x1f447) + ' Choose:')), 'inline_buttons': buttons}
            for opt in opts:
                ofk = str(opt.get('flow', ''))
                if ofk and ofk not in flows:
                    of = {'reply': str(opt.get('reply', chr(0x2705) + ' Selected!')), 'show_menu': True}
                    if opt.get('set_vars'): of['set_vars'] = dict(opt['set_vars'])
                    flows[ofk] = of
    bot_d = {
        'name': name, 'platform': 'telegram', 'welcome': welcome,
        'default_reply': default_reply, 'menu': menu[:4], 'flows': flows
    }
    if user_vars_d: bot_d['user_vars'] = user_vars_d
    if photo_flow_key: bot_d['photo_flow'] = photo_flow_key
    return pyyaml.dump({'bot': bot_d}, allow_unicode=True, default_flow_style=False, indent=2)


def _call_ai_spec(api_key, provider, desc, bot_name):
    """Step 1: AI returns JSON spec. No DSL knowledge required from AI."""
    import json as _jmod
    prompt = (
        'Analyze this Telegram bot. Output ONLY a valid JSON object.\n'
        'Bot name: ' + bot_name + '\n'
        'Description: ' + desc + '\n\n'
        '{\n'
        '  "name": "Bot Name with emoji",\n'
        '  "welcome": "Welcome message",\n'
        '  "default_reply": "Please use the menu.",\n'
        '  "user_vars": {},\n'
        '  "flows": [\n'
        '    {"key": "snake_key", "menu_text": "emoji Text", "type": "TYPE", ...extras}\n'
        '  ]\n'
        '}\n\n'
        'FLOW TYPES AND REQUIRED EXTRAS:\n'
        '- "static": for help/about/contacts/info. Add: "content": "your text here"\n'
        '- "ai_chat": AI Q&A conversation. Add: "ask": "question?", "system_prompt": "You are..."\n'
        '- "language_choice": language picker menu. Add: "var": "lang", "languages": ["Russian","English","Spanish","French","German","Chinese"]\n'
        '- "vision_translate": OCR+translate photo. Add: "target_lang_var": "lang", "is_photo_flow": true\n'
        '- "text_translate": translate typed text. Add: "target_lang_var": "lang"\n'
        '- "collect_input": collect user data. Add: "ask": "question?", "reply": "Thank you!"\n'
        '- "inline_choice": pick from options. Add: "ask": "Choose:", "options": [{"text": "emoji A", "flow": "opt_a", "reply": "Done!"}]\n\n'
        'RULES:\n'
        '1. Max 4 menu flows (sub-flows not counted)\n'
        '2. If translation + language mentioned -> add language_choice + user_vars: {"lang": "Russian"}\n'
        '3. Photo/image translation -> vision_translate with is_photo_flow: true\n'
        '4. Text translation -> text_translate\n'
        '5. Always include a static help flow\n'
        '6. Output ONLY the JSON object'
    )
    try:
        if provider in ('anthropic', 'claude'):
            r = req.post('https://api.anthropic.com/v1/messages',
                headers={'x-api-key': api_key, 'anthropic-version': '2023-06-01',
                         'content-type': 'application/json'},
                json={'model': 'claude-sonnet-4-5', 'max_tokens': 2048,
                      'messages': [{'role': 'user', 'content': prompt}]},
                timeout=60)
            if not r.ok: return None, f'Anthropic {r.status_code}: {r.text[:100]}'
            text = r.json()['content'][0]['text'].strip()
        else:
            r = req.post('https://api.openai.com/v1/chat/completions',
                headers={'Authorization': 'Bearer ' + api_key},
                json={'model': 'gpt-4o', 'max_tokens': 2048, 'temperature': 0.1,
                      'response_format': {'type': 'json_object'},
                      'messages': [{'role': 'user', 'content': prompt}]},
                timeout=60)
            if not r.ok: return None, f'OpenAI {r.status_code}: {r.text[:100]}'
            text = r.json()['choices'][0]['message']['content']
        # Parse JSON — find first { to end
        start = text.find('{')
        if start >= 0: text = text[start:]
        return _jmod.loads(text), None
    except Exception as e:
        return None, str(e)




# --- COMPAT STUBS (for add_feature fallback) ---
def _detect_choices(d): return []
def _build_smart_prompt(d, n, det, t=None): return d
def _build_patch_prompt(e, d, det): return d
def _call_ai_generate(k, p, prompt, use_sonnet=False): return None
def _clean_yaml_from_ai(raw): return (raw or '').strip()


@app.route('/api/generate', methods=['POST'])
def generate_yaml():
    data = request.json or {}
    desc = (data.get('description') or '').strip()
    api_key = (data.get('api_key') or '').strip()
    provider = str(data.get('ai_provider', 'anthropic'))
    bot_name = (data.get('bot_name') or 'My Bot').strip()
    if not desc: return jsonify({'error': 'description required'}), 400
    has_ai = bool(data.get('ai_api_key') or api_key)
    if not api_key:
        return jsonify({'ok': True, 'yaml': _make_simple_template(bot_name, desc, has_ai),
                        'source': 'template', 'warnings': []})
    try:
        # STEP 1: AI understands bot description → JSON spec
        spec, spec_err = _call_ai_spec(api_key, provider, desc, bot_name)
        if not spec:
            warn = 'AI analysis failed: ' + str(spec_err) + '. Using simple template.'
            return jsonify({'ok': True, 'yaml': _make_simple_template(bot_name, desc, has_ai),
                            'source': 'template', 'warnings': [warn]})
        # STEP 2: Python deterministic builder → always valid DSL YAML
        yaml_out = _spec_to_yaml(spec)
        try:
            pyyaml.safe_load(yaml_out)
        except Exception as _ye:
            return jsonify({'ok': True, 'yaml': _make_simple_template(bot_name, desc, has_ai),
                            'source': 'template', 'warnings': ['YAML build error: ' + str(_ye)]})
        clean, warnings = _sanitize_yaml(yaml_out)
        return jsonify({'ok': True, 'yaml': clean, 'source': 'spec', 'warnings': warnings})
    except Exception as _gen_e:
        print('[generate_yaml] ERROR: ' + str(_gen_e))
        import traceback; traceback.print_exc()
        return jsonify({'ok': True,
                        'yaml': _make_simple_template(bot_name, desc, has_ai),
                        'source': 'template',
                        'warnings': ['Error: ' + str(_gen_e)[:120]]})



@app.route('/api/bots/<bot_id>/diagnose', methods=['GET'])
def diagnose_bot(bot_id):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT * FROM bots WHERE id=%s', (bot_id,))
            bot = cur.fetchone()
    finally:
        conn.close()
    if not bot:
        return jsonify({'error': 'Bot not found'}), 404
    bot = dict(bot)
    tok = bot.get('bot_token', '')
    diag = {
        'id': bot_id,
        'name': bot.get('name'),
        'status': bot.get('status'),
        'has_yaml': bool(bot.get('yaml_definition')),
        'yaml_len': len(bot.get('yaml_definition') or ''),
        'has_ai_key': bool(bot.get('ai_api_key')),
        'token_hash': (bot.get('bot_token_hash') or '')[:16],
        'expected_webhook': f'{RAILWAY_URL}/bot/{bot.get("bot_token_hash","")}'
    }
    if tok:
        try:
            wh = req.get(f'https://api.telegram.org/bot{tok}/getWebhookInfo', timeout=8).json().get('result', {})
            diag['webhook_set'] = wh.get('url', '')
            diag['webhook_matches'] = wh.get('url') == diag['expected_webhook']
            diag['pending_updates'] = wh.get('pending_update_count', 0)
            diag['last_error'] = wh.get('last_error_message', '')
        except Exception as e:
            diag['webhook_error'] = str(e)
        try:
            me = req.get(f'https://api.telegram.org/bot{tok}/getMe', timeout=8).json()
            diag['token_valid'] = me.get('ok', False)
        except Exception as e:
            diag['token_error'] = str(e)
        yaml_def = bot.get('yaml_definition', '')
        if yaml_def:
            try:
                cfg = pyyaml.safe_load(yaml_def)
                bc = cfg.get('bot', cfg) if cfg else {}
                diag['yaml_ok'] = True
                diag['flows'] = list(bc.get('flows', {}).keys())
            except Exception as e:
                diag['yaml_ok'] = False
                diag['yaml_error'] = str(e)
    issues = []
    if not diag.get('webhook_matches'):
        issues.append(f'Webhook mismatch! Set: {diag.get("webhook_set","none")[:60]}')
    if not diag.get('yaml_ok', True):
        issues.append(f'YAML broken: {diag.get("yaml_error")}')
    if not diag.get('token_valid', True):
        issues.append('Bot token INVALID')
    if bot.get('status') != 'active':
        issues.append('Bot is INACTIVE')
    diag['issues'] = issues
    diag['diagnosis'] = 'OK' if not issues else f'{len(issues)} PROBLEMS'
    return jsonify({'ok': True, 'diagnostic': diag})


@app.route('/api/bots/<bot_id>/fix_webhook', methods=['POST'])
def fix_webhook(bot_id):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT * FROM bots WHERE id=%s', (bot_id,))
            bot = cur.fetchone()
    finally:
        conn.close()
    if not bot:
        return jsonify({'error': 'Not found'}), 404
    bot = dict(bot)
    if not RAILWAY_URL:
        return jsonify({'error': 'RAILWAY_URL not configured'}), 500
    wh_url = f'{RAILWAY_URL}/bot/{bot["bot_token_hash"]}'
    r = req.post(f'https://api.telegram.org/bot{bot["bot_token"]}/setWebhook',
        json={'url': wh_url, 'drop_pending_updates': True}, timeout=10)
    if r.ok and r.json().get('ok'):
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute("UPDATE bots SET status='active', updated_at=NOW() WHERE id=%s", (bot_id,))
            conn.commit()
        finally:
            conn.close()
        return jsonify({'ok': True, 'webhook_url': wh_url})
    return jsonify({'error': 'setWebhook failed', 'detail': r.json()}), 500


@app.route('/api/bots/<bot_id>/yaml', methods=['GET'])
def get_bot_yaml(bot_id):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT yaml_definition, yaml_backup FROM bots WHERE id=%s', (bot_id,))
            row = cur.fetchone()
    finally: conn.close()
    if not row: return jsonify({'error': 'Not found'}), 404
    return jsonify({'ok': True, 'yaml': row['yaml_definition'] or '',
                    'has_backup': bool(row.get('yaml_backup'))})


@app.route('/api/bots/<bot_id>/apply_patch', methods=['POST'])
def apply_patch(bot_id):
    data = request.json or {}
    new_yaml = data.get('yaml', '')
    if not new_yaml: return jsonify({'error': 'yaml required'}), 400
    new_yaml, warnings = _sanitize_yaml(new_yaml)
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT yaml_definition FROM bots WHERE id=%s', (bot_id,))
            row = cur.fetchone()
            old_yaml = row['yaml_definition'] if row else ''
            cur.execute('UPDATE bots SET yaml_definition=%s, yaml_backup=%s, updated_at=NOW() WHERE id=%s',
                (new_yaml, old_yaml, bot_id))
        conn.commit()
    finally: conn.close()
    return jsonify({'ok': True, 'message': 'Changes applied!', 'warnings': warnings})


@app.route('/api/bots/<bot_id>/revert_yaml', methods=['POST'])
def revert_yaml_ep(bot_id):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT yaml_definition, yaml_backup FROM bots WHERE id=%s', (bot_id,))
            row = cur.fetchone()
    finally: conn.close()
    if not row or not (row.get('yaml_backup') or '').strip():
        return jsonify({'error': 'No backup available'}), 400
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute('UPDATE bots SET yaml_definition=%s, yaml_backup=%s, updated_at=NOW() WHERE id=%s',
                (row['yaml_backup'], '', bot_id))
        conn.commit()
    finally: conn.close()
    return jsonify({'ok': True, 'message': 'Reverted to previous version!'})


@app.route('/api/bots/<bot_id>/add_feature', methods=['POST'])
def add_feature(bot_id):
    data = request.json or {}
    desc = (data.get('description') or '').strip()
    api_key = (data.get('api_key') or '').strip()
    provider = data.get('ai_provider', 'anthropic')
    if not desc: return jsonify({'error': 'description required'}), 400
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT yaml_definition, ai_api_key, ai_provider FROM bots WHERE id=%s', (bot_id,))
            bot = cur.fetchone()
    finally: conn.close()
    if not bot: return jsonify({'error': 'Bot not found'}), 404
    bot = dict(bot)
    existing = bot.get('yaml_definition', '')
    if not existing: return jsonify({'error': 'Bot has no YAML. Use Rebuild Bot instead.'}), 400
    if not api_key: api_key = bot.get('ai_api_key', ''); provider = bot.get('ai_provider', 'anthropic')
    if not api_key: return jsonify({'error': 'API key required. Add it in bot settings.'}), 400
    detected = _detect_choices(desc)
    prompt = _build_patch_prompt(existing, desc, detected)
    raw = _call_ai_generate(api_key, provider, prompt, use_sonnet=True)
    if not raw: return jsonify({'error': 'AI generation failed. Check your API key.'}), 500
    yt = _clean_yaml_from_ai(raw)
    if not yt: return jsonify({'error': 'Could not parse AI response'}), 500
    try: pyyaml.safe_load(yt)
    except Exception as e: return jsonify({'error': f'Generated YAML invalid: {e}'}), 500
    clean, warnings = _sanitize_yaml(yt)
    diff = _diff_yamls(existing, clean)
    return jsonify({'ok': True, 'new_yaml': clean, 'diff': diff, 'warnings': warnings,
                    'detected_choices': detected})


@app.route('/api/bots/<bot_id>/rebuild', methods=['POST'])
def rebuild_bot(bot_id):
    data = request.json or {}
    desc = (data.get('description') or '').strip()
    api_key = (data.get('api_key') or '').strip()
    provider = data.get('ai_provider', 'anthropic')
    if not desc: return jsonify({'error': 'description required'}), 400
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT name, ai_api_key, ai_provider FROM bots WHERE id=%s', (bot_id,))
            bot = cur.fetchone()
    finally: conn.close()
    if not bot: return jsonify({'error': 'Bot not found'}), 404
    bot = dict(bot)
    if not api_key: api_key = bot.get('ai_api_key', ''); provider = bot.get('ai_provider', 'anthropic')
    if not api_key: return jsonify({'error': 'API key required. Add it in bot settings.'}), 400
    # 2-step generation for rebuild
    spec, spec_err = _call_ai_spec(api_key, provider, desc, bot.get('name', 'My Bot'))
    if not spec:
        return jsonify({'ok': True, 'yaml': _make_simple_template(bot.get('name', 'My Bot'), desc, True),
                        'source': 'template', 'warnings': ['AI spec: ' + str(spec_err)]})
    raw_yaml = _spec_to_yaml(spec)
    raw = raw_yaml  # compat
    if not raw: return jsonify({'error': 'AI generation failed. Check your API key.'}), 500
    yt = _clean_yaml_from_ai(raw)
    if not yt: return jsonify({'error': 'Could not parse AI response'}), 500
    try: pyyaml.safe_load(yt)
    except Exception as e: return jsonify({'error': f'Invalid YAML: {e}'}), 500
    clean, warnings = _sanitize_yaml(yt)
    return jsonify({'ok': True, 'yaml': clean, 'warnings': warnings, 'detected_choices': detected})




def _make_simple_template(name, desc, has_ai=False):
    q = chr(34); n = str(name or 'Bot').replace(chr(34), chr(39))
    d = str(desc or '')[:80].replace(chr(34), chr(39))
    if has_ai:
        lines = [
            'bot:', f'  name: {q}{n}{q}', '  platform: telegram',
            f'  welcome: {q}' + chr(0x1f44b) + f' Hello! I am {n}.{q}',
            f'  default_reply: {q}Send a message or use the menu.{q}', '  menu:',
            f'    - text: {q}' + chr(0x1f4ac) + f' Chat{q}', '      flow: ai_chat',
            f'    - text: {q}' + chr(0x1f4f7) + f' Send Photo{q}', '      flow: photo',
            f'    - text: {q}' + chr(0x2753) + f' Help{q}', '      flow: help',
            '  flows:', '    ai_chat:',
            f'      ask: {q}What would you like to know?{q}',
            '      on_input:', '        call_ai:',
            f'          system: {q}You are a helpful assistant. Context: {d}{q}',
            f'          prompt: {q}' + '{{input}}' + f'{q}',
            f'        reply: {q}' + '{{ai_result}}' + f'{q}', '        show_menu: true',
            '    photo:', f'      ask: {q}Send a photo:{q}',
            '      on_input:', '        call_ai_vision:',
            f'          prompt: {q}Describe and analyze this image.{q}',
            f'        reply: {q}' + '{{ai_result}}' + f'{q}', '        show_menu: true',
            '    help:',
            f'      reply: {q}' + chr(0x1f4a1) + f' I am {n}. {d}{q}', '      show_menu: true']
    else:
        lines = [
            'bot:', f'  name: {q}{n}{q}', '  platform: telegram',
            f'  welcome: {q}' + chr(0x1f44b) + f' Welcome! I am {n}.{q}',
            f'  default_reply: {q}Please use the menu.{q}', '  menu:',
            f'    - text: {q}' + chr(0x2139) + chr(0xfe0f) + f' About{q}', '      flow: about',
            f'    - text: {q}' + chr(0x1f4de) + f' Contact{q}', '      flow: contact',
            f'    - text: {q}' + chr(0x2753) + f' Help{q}', '      flow: help',
            '  flows:', '    about:',
            f'      reply: {q}' + chr(0x2139) + chr(0xfe0f) + f' {d}{q}', '      show_menu: true',
            '    contact:', f'      ask: {q}' + chr(0x1f4de) + f' Send your message:{q}',
            '      on_input:',
            f'        reply: {q}' + chr(0x2705) + ' Received: {{input}}' + f'{q}',
            '        show_menu: true', '    help:',
            f'      reply: {q}' + chr(0x2753) + f' Use menu buttons to navigate.{q}',
            '      show_menu: true']
    return chr(10).join(lines)


def _tg_send(token, chat_id, text, markup=None):
    d = {'chat_id': chat_id, 'text': str(text) or '.', 'parse_mode': 'HTML'}
    if markup:
        d['reply_markup'] = markup
    try:
        req.post(f'https://api.telegram.org/bot{token}/sendMessage', json=d, timeout=10)
    except Exception:
        pass


def _build_keyboard(menu):
    if not menu:
        return None
    rows, row = [], []
    for item in menu:
        row.append({'text': item.get('text', '')})
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)
    return {'keyboard': rows, 'resize_keyboard': True}


def _send_with_menu(token, chat_id, text, menu):
    kb = _build_keyboard(menu)
    d = {'chat_id': chat_id, 'text': str(text) or '.', 'parse_mode': 'HTML'}
    if kb:
        d['reply_markup'] = kb
    try:
        req.post(f'https://api.telegram.org/bot{token}/sendMessage', json=d, timeout=10)
    except Exception:
        pass


def _get_state(bot_id, chat_id, key):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT state_value FROM bot_states WHERE bot_id=%s AND chat_id=%s AND state_key=%s',
                (bot_id, str(chat_id), key))
            row = cur.fetchone()
            return row['state_value'] if row else ''
    except Exception:
        return ''
    finally:
        conn.close()


def _set_state(bot_id, chat_id, key, value):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                '''INSERT INTO bot_states (bot_id,chat_id,state_key,state_value)
                VALUES (%s,%s,%s,%s) ON CONFLICT (bot_id,chat_id,state_key)
                DO UPDATE SET state_value=EXCLUDED.state_value,updated_at=NOW()''',
                (bot_id, str(chat_id), key, value))
        conn.commit()
    except Exception as e:
        print(f'[state] {e}')
    finally:
        conn.close()


def _get_photo_url(token, file_id):
    try:
        r = req.get(f'https://api.telegram.org/bot{token}/getFile',
            params={'file_id': file_id}, timeout=10)
        if r.ok:
            return f'https://api.telegram.org/file/bot{token}/{r.json()["result"]["file_path"]}'
    except Exception:
        pass
    return None


def _ai_text(api_key, provider, system, user_msg):
    if not api_key:
        return chr(0x26a0) + ' AI key not configured. Add it in bot settings.'
    try:
        if provider == 'openai':
            r = req.post('https://api.openai.com/v1/chat/completions',
                headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
                json={'model': 'gpt-4o-mini', 'max_tokens': 2000,
                      'messages': [{'role': 'system', 'content': system},
                                   {'role': 'user', 'content': user_msg}]}, timeout=60)
            return r.json()['choices'][0]['message']['content'] if r.ok else f'AI error {r.status_code}'
        else:
            r = req.post('https://api.anthropic.com/v1/messages',
                headers={'x-api-key': api_key, 'anthropic-version': '2023-06-01',
                         'content-type': 'application/json'},
                json={'model': HAIKU_MODEL, 'max_tokens': 2000, 'system': system,
                      'messages': [{'role': 'user', 'content': user_msg}]}, timeout=60)
            return r.json()['content'][0]['text'] if r.ok else f'AI error {r.status_code}'
    except Exception as e:
        return f'AI error: {e}'


def _ai_vision(api_key, provider, prompt, img_url):
    if not api_key:
        return chr(0x26a0) + ' AI key not configured. Add it in bot settings.'
    if not img_url:
        return chr(0x26a0) + ' Could not download image from Telegram.'
    try:
        if provider == 'openai':
            r = req.post('https://api.openai.com/v1/chat/completions',
                headers={'Authorization': f'Bearer {api_key}', 'Content-Type': 'application/json'},
                json={'model': 'gpt-4o-mini', 'max_tokens': 2000,
                      'messages': [{'role': 'user', 'content': [
                          {'type': 'text', 'text': prompt},
                          {'type': 'image_url', 'image_url': {'url': img_url, 'detail': 'high'}}
                      ]}]}, timeout=90)
            return r.json()['choices'][0]['message']['content'] if r.ok else f'Vision error {r.status_code}'
        else:
            img_r = req.get(img_url, timeout=30)
            if not img_r.ok:
                return 'Could not download image.'
            img_b64 = b64mod.b64encode(img_r.content).decode()
            mt = img_r.headers.get('content-type', 'image/jpeg').split(';')[0]
            r = req.post('https://api.anthropic.com/v1/messages',
                headers={'x-api-key': api_key, 'anthropic-version': '2023-06-01',
                         'content-type': 'application/json'},
                json={'model': HAIKU_MODEL, 'max_tokens': 2000,
                      'messages': [{'role': 'user', 'content': [
                          {'type': 'image', 'source': {'type': 'base64', 'media_type': mt, 'data': img_b64}},
                          {'type': 'text', 'text': prompt}
                      ]}]}, timeout=90)
            return r.json()['content'][0]['text'] if r.ok else f'Vision error {r.status_code}'
    except Exception as e:
        return f'Vision error: {e}'


def _sub_vars(text, user_input=None, ai_result=None, user_vars=None):
    t = str(text)
    now = datetime.now()
    t = t.replace('{{today}}', now.strftime('%d.%m.%Y'))
    t = t.replace('{{date}}', now.strftime('%d.%m.%Y'))
    t = t.replace('{{month}}', now.strftime('%B'))
    t = t.replace('{{year}}', str(now.year))
    t = t.replace('{{time}}', now.strftime('%H:%M'))
    if user_input is not None:
        t = t.replace('{{input}}', str(user_input))
    if ai_result is not None:
        t = t.replace('{{ai_result}}', str(ai_result))
        t = t.replace('{{result}}', str(ai_result))
    if user_vars:
        for _k, _v in user_vars.items():
            t = t.replace('{{user_var:' + _k + '}}', str(_v))
    return t




def _get_user_vars(bot_id, chat_id, user_vars_cfg):
    result = {}
    for key, default in (user_vars_cfg or {}).items():
        val = _get_state(bot_id, str(chat_id), 'uvar_' + str(key))
        result[str(key)] = val if val else str(default)
    return result


def _set_user_var(bot_id, chat_id, key, value):
    _set_state(bot_id, str(chat_id), 'uvar_' + str(key), str(value))


def _exec_on_input(token, on_input, chat_id, ai_key, ai_prov, user_text=None, photo_fid=None, user_vars=None, bot_id=None):
    ai_result = None
    if 'user_var_set' in on_input and user_text is not None and bot_id:
        _set_user_var(bot_id, str(chat_id), str(on_input['user_var_set']), str(user_text))
        if user_vars is not None:
            user_vars[str(on_input['user_var_set'])] = str(user_text)
    has_ai_call = any(k in on_input for k in [
        'call_ai', 'call_openai', 'call_anthropic',
        'call_ai_vision', 'call_openai_vision', 'call_anthropic_vision'])
    loading = on_input.get('loading_text', '')
    if has_ai_call and ai_key:
        _tg_send(token, chat_id, loading if loading else chr(0x23f3) + ' Processing...')
    if user_text is not None:
        for call_key, prov in [('call_ai', ai_prov), ('call_openai', 'openai'), ('call_anthropic', 'anthropic')]:
            if call_key in on_input:
                c = on_input[call_key] if isinstance(on_input[call_key], dict) else {}
                ai_result = _ai_text(ai_key, prov,
                    _sub_vars(c.get('system', 'You are a helpful assistant.'), user_vars=user_vars),
                    _sub_vars(c.get('prompt', '{{input}}'), user_input=user_text, user_vars=user_vars))
                break
        if ai_result is None and '{{ai_result}}' in str(on_input.get('reply', '')):
            ai_result = _ai_text(ai_key, ai_prov, 'You are a helpful assistant.', user_text) if ai_key else chr(0x26a0) + ' AI key not configured.'
    if photo_fid is not None:
        img_url = _get_photo_url(token, photo_fid)
        found_vision = False
        for vkey, prov in [('call_ai_vision', ai_prov), ('call_openai_vision', 'openai'), ('call_anthropic_vision', 'anthropic')]:
            if vkey in on_input:
                c = on_input[vkey] if isinstance(on_input[vkey], dict) else {}
                _vis_p = _sub_vars(c.get('prompt', 'Describe this image.'), user_vars=user_vars)
                ai_result = _ai_vision(ai_key, prov, _vis_p, img_url)
                found_vision = True; break
        if not found_vision:
            vp = _sub_vars(on_input.get('vision_prompt', 'Describe this image.'), user_vars=user_vars)
            ai_result = _ai_vision(ai_key, ai_prov, vp, img_url) if ai_key else chr(0x26a0) + ' AI key needed for photo analysis.'
    tpl = str(on_input.get('reply', ''))
    if tpl:
        if ai_result and '{{ai_result}}' not in tpl and '{{result}}' not in tpl:
            tpl = tpl + '\n' + str(ai_result)
        reply = _sub_vars(tpl, user_input=user_text, ai_result=ai_result, user_vars=user_vars)
        if on_input.get('inline_buttons'):
            try:
                _ibtns = [[{'text': b['text'], 'callback_data': b.get('flow', b['text'])}
                            for b in on_input['inline_buttons']]]
                req.post(f'https://api.telegram.org/bot{token}/sendMessage',
                    json={'chat_id': chat_id, 'text': reply,
                          'reply_markup': {'inline_keyboard': _ibtns}}, timeout=10)
                return None, bool(on_input.get('show_menu')), str(on_input.get('next_flow', ''))
            except Exception as _ie:
                print(f'[ibtns] {_ie}')
        return reply, bool(on_input.get('show_menu')), str(on_input.get('next_flow', ''))
    if ai_result:
        if on_input.get('inline_buttons'):
            try:
                _ibtns = [[{'text': b['text'], 'callback_data': b.get('flow', b['text'])}
                            for b in on_input['inline_buttons']]]
                req.post(f'https://api.telegram.org/bot{token}/sendMessage',
                    json={'chat_id': chat_id, 'text': str(ai_result),
                          'reply_markup': {'inline_keyboard': _ibtns}}, timeout=10)
                return None, bool(on_input.get('show_menu')), str(on_input.get('next_flow', ''))
            except Exception as _ie:
                print(f'[ibtns_ai] {_ie}')
        return str(ai_result), bool(on_input.get('show_menu')), str(on_input.get('next_flow', ''))
    return None, False, ''


def _run_flow(bot, token, chat_id, flows, flow_key, menu, ai_key, ai_prov, user_text=None, photo_fid=None, user_vars=None):
    flow = flows.get(flow_key)
    if not flow or not isinstance(flow, dict):
        print(f'[flow] Key not found: {flow_key}')
        return
    bot_id = bot['id']
    # set_vars: set user variables from button flow (no user input needed)
    _sv = flow.get('set_vars', {})
    if _sv and isinstance(_sv, dict):
        for _svk, _svv in _sv.items():
            _set_user_var(bot_id, str(chat_id), str(_svk), str(_svv))
            if user_vars is not None:
                user_vars[str(_svk)] = str(_svv)
    if photo_fid is not None and flow.get('handle_photo'):
        img_url = _get_photo_url(token, photo_fid)
        if ai_key and img_url:
            _tg_send(token, chat_id, chr(0x23f3) + ' Analyzing image...')
            c = flow.get('call_ai_vision', {})
            prompt = c.get('prompt', 'Describe this image.') if isinstance(c, dict) else 'Describe this image.'
            prompt = _sub_vars(prompt, user_vars=user_vars)
            ai_result = _ai_vision(ai_key, ai_prov, prompt, img_url)
        else:
            ai_result = chr(0x26a0) + ' AI key not configured. Add in bot settings.'
        reply = _sub_vars(str(flow.get('reply', '{{ai_result}}')), ai_result=ai_result)
        if flow.get('show_menu'):
            _send_with_menu(token, chat_id, reply, menu)
        else:
            _tg_send(token, chat_id, reply)
        nf = str(flow.get('next_flow', ''))
        if nf and nf in flows:
            _run_flow(bot, token, chat_id, flows, nf, menu, ai_key, ai_prov, user_vars=user_vars)
        return
    if 'ask' in flow and user_text is None and photo_fid is None:
        if 'inline_buttons' in flow:
            try:
                btns = [[{'text': b['text'], 'callback_data': b.get('flow', b['text'])}
                         for b in flow['inline_buttons']]]
                req.post(f'https://api.telegram.org/bot{token}/sendMessage',
                    json={'chat_id': chat_id, 'text': flow['ask'],
                          'reply_markup': {'inline_keyboard': btns}}, timeout=10)
            except Exception as _e:
                print(f'[inline_ask] {_e}')
                _tg_send(token, chat_id, flow['ask'])
        else:
            _tg_send(token, chat_id, flow['ask'])
        if 'on_input' in flow:
            _set_state(bot_id, str(chat_id), f'oi_{flow_key}', json.dumps(flow['on_input']))
        _set_state(bot_id, str(chat_id), 'waiting', flow_key)
        return
    if 'reply' in flow:
        reply = _sub_vars(str(flow['reply']), user_input=user_text, user_vars=user_vars)
        if flow.get('show_menu'):
            _send_with_menu(token, chat_id, reply, menu)
        else:
            _tg_send(token, chat_id, reply)
    if 'inline_buttons' in flow:
        try:
            btns_text = flow.get('ask') or flow.get('reply') or 'Choose:'
            btns = [[{'text': b['text'], 'callback_data': b.get('flow', b['text'])}
                     for b in flow['inline_buttons']]]
            req.post(f'https://api.telegram.org/bot{token}/sendMessage',
                json={'chat_id': chat_id, 'text': btns_text,
                      'reply_markup': {'inline_keyboard': btns}}, timeout=10)
        except Exception as e:
            print(f'[inline_btns] {e}')
    nf = str(flow.get('next_flow', ''))
    if nf and nf in flows:
        _run_flow(bot, token, chat_id, flows, nf, menu, ai_key, ai_prov, user_vars=user_vars)


def _handle_yaml_bot(bot, update):
    bot_id = bot['id']; token = bot['bot_token']
    ai_key = str(bot.get('ai_api_key') or '')
    ai_prov = str(bot.get('ai_provider') or 'anthropic')
    yaml_def = bot.get('yaml_definition') or ''
    if not yaml_def:
        print(f'[bot:{bot_id}] EMPTY YAML')
        return
    try:
        cfg = pyyaml.safe_load(yaml_def)
        if not cfg: return
        bc = cfg.get('bot', cfg)
    except Exception as e:
        print(f'[bot:{bot_id}] YAML ERROR: {e}')
        return
    flows = bc.get('flows', {}); menu = bc.get('menu', [])
    default_reply = bc.get('default_reply', 'Please use the menu.')
    user_vars_cfg = bc.get('user_vars', {})
    if 'callback_query' in update:
        cq = update['callback_query']; cid = str(cq['message']['chat']['id'])
        fk = cq.get('data', '')
        try:
            req.post(f'https://api.telegram.org/bot{token}/answerCallbackQuery',
                json={'callback_query_id': cq['id']}, timeout=5)
        except Exception: pass
        _set_state(bot_id, cid, 'waiting', '')
        if fk in flows:
            _run_flow(bot, token, cid, flows, fk, menu, ai_key, ai_prov, user_vars={})
        return
    msg = update.get('message', {})
    if not msg: return
    cid = str(msg['chat']['id']); text = msg.get('text', ''); photo = msg.get('photo')
    if text == '/start':
        _set_state(bot_id, cid, 'waiting', '')
        for _k, _v in (user_vars_cfg or {}).items():
            if not _get_state(bot_id, cid, 'uvar_' + str(_k)):
                _set_state(bot_id, cid, 'uvar_' + str(_k), str(_v))
        welcome_vars = _get_user_vars(bot_id, cid, user_vars_cfg)
        welcome = _sub_vars(str(bc.get('welcome', 'Welcome! ' + chr(0x1f916))), user_vars=welcome_vars)
        kb = _build_keyboard(menu)
        d = {'chat_id': cid, 'text': welcome, 'parse_mode': 'HTML'}
        if kb: d['reply_markup'] = kb
        try: req.post(f'https://api.telegram.org/bot{token}/sendMessage', json=d, timeout=10)
        except Exception: pass
        return
    if text == '/help':
        _send_with_menu(token, cid, 'Use the menu buttons to interact.', menu); return
    user_vars = _get_user_vars(bot_id, cid, user_vars_cfg)
    if photo:
        pfid = photo[-1]['file_id']
        waiting = _get_state(bot_id, cid, 'waiting')
        if waiting:
            oi_str = _get_state(bot_id, cid, f'oi_{waiting}')
            if oi_str:
                try:
                    on_input = json.loads(oi_str)
                    _set_state(bot_id, cid, 'waiting', '')
                    reply, sm, nf = _exec_on_input(token, on_input, cid, ai_key, ai_prov, user_text=None, photo_fid=pfid, user_vars=user_vars, bot_id=bot_id)
                    if reply:
                        if sm: _send_with_menu(token, cid, reply, menu)
                        else: _tg_send(token, cid, reply)
                    elif not ai_key: _send_with_menu(token, cid, chr(0x26a0) + ' Add AI key in bot settings.', menu)
                    if nf and nf in flows:
                        _run_flow(bot, token, cid, flows, nf, menu, ai_key, ai_prov, user_vars=user_vars)
                    return
                except Exception as e:
                    print(f'[photo_input] {e}'); _set_state(bot_id, cid, 'waiting', '')
        pf_key = str(bc.get('photo_flow', ''))
        if not pf_key:
            for fk, fv in flows.items():
                if isinstance(fv, dict) and fv.get('handle_photo'):
                    pf_key = fk; break
        if pf_key and pf_key in flows:
            _run_flow(bot, token, cid, flows, pf_key, menu, ai_key, ai_prov, photo_fid=pfid, user_vars=user_vars); return
        if ai_key:
            img_url = _get_photo_url(token, pfid)
            if img_url:
                _tg_send(token, cid, chr(0x23f3) + ' Analyzing your image...')
                result = _ai_vision(ai_key, ai_prov, 'Describe this image. If there is text, extract it.', img_url)
                _send_with_menu(token, cid, result, menu); return
        _send_with_menu(token, cid, chr(0x1f4f7) + ' Photo received! Add AI key to analyze.', menu); return
    if not text: return
    for item in menu:
        if item.get('text') == text:
            fk = str(item.get('flow', ''))
            if fk in flows:
                _set_state(bot_id, cid, 'waiting', '')
                _run_flow(bot, token, cid, flows, fk, menu, ai_key, ai_prov, user_vars=user_vars); return
    waiting = _get_state(bot_id, cid, 'waiting')
    if waiting:
        oi_str = _get_state(bot_id, cid, f'oi_{waiting}')
        _set_state(bot_id, cid, 'waiting', '')
        if oi_str:
            try:
                on_input = json.loads(oi_str)
                reply, sm, nf = _exec_on_input(token, on_input, cid, ai_key, ai_prov, user_text=text, user_vars=user_vars, bot_id=bot_id)
                if reply:
                    if sm: _send_with_menu(token, cid, reply, menu)
                    else: _tg_send(token, cid, reply)
                if nf and nf in flows:
                    _run_flow(bot, token, cid, flows, nf, menu, ai_key, ai_prov, user_vars=user_vars)
                return
            except Exception as e:
                print(f'[text_input] {e}')
    _send_with_menu(token, cid, default_reply, menu)



@app.route('/webhook', methods=['POST'])
def botbuilder_webhook():
    if not BOTBUILDER_TOKEN:
        return 'ok'
    update = request.json or {}
    try:
        msg = update.get('message', {})
        cid = msg.get('chat', {}).get('id')
        if not cid:
            return 'ok'
        mu = f'{RAILWAY_URL}/app' if RAILWAY_URL else ''
        wave = chr(0x1f44b)
        robot = chr(0x1f916)
        if mu:
            welcome_text = wave + ' Welcome to <b>BotBuilder</b>!\n\nCreate Telegram bots in minutes.\nTap below:'
            kb = {'inline_keyboard': [[{'text': robot + ' Open BotBuilder', 'web_app': {'url': mu}}]]}
            _tg_send(BOTBUILDER_TOKEN, cid, welcome_text, kb)
        else:
            _tg_send(BOTBUILDER_TOKEN, cid, wave + ' Welcome to BotBuilder!')
    except Exception as e:
        print(f'[bb] {e}')
    return 'ok'


@app.route('/bot/<token_hash>', methods=['POST'])
def user_bot_webhook(token_hash):
    update = request.json or {}
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM bots WHERE bot_token_hash=%s AND status='active'", (token_hash,))
            bot = cur.fetchone()
    finally:
        conn.close()
    if not bot:
        return 'ok'
    try:
        _handle_yaml_bot(dict(bot), update)
    except Exception as e:
        print(f'[bot] {e}')
    return 'ok'


try:
    if DATABASE_URL:
        init_db()
except Exception as e:
    print(f'[startup] {e}')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
