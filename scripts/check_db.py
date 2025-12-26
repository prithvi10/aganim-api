import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Load .env from the root of the project
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    print("DATABASE_URL not found in environment or .env file.")
else:
    # Obfuscate password for printing
    display_url = DATABASE_URL
    if "@" in display_url:
        parts = display_url.split("@")
        cred_parts = parts[0].split(":")
        if len(cred_parts) > 2:
            display_url = f"{cred_parts[0]}:{cred_parts[1]}:****@{parts[1]}"
    
    print(f"Connecting to: {display_url}")
    
    engine = create_engine(DATABASE_URL)
    
    with engine.connect() as conn:
        print("\n--- ALL PLANS ---")
        plans = conn.execute(text("SELECT id, name, monthly_token_quota, max_request_rate FROM plans")).fetchall()
        for plan in plans:
            print(f"ID: {plan.id} | Name: {plan.name} | Quota: {plan.monthly_token_quota} | Rate: {plan.max_request_rate}")
            
        print("\n--- ALL USERS AND THEIR PLANS ---")
        users = conn.execute(text("SELECT u.username, p.name as plan_name FROM users u JOIN plans p ON u.plan_id = p.id")).fetchall()
        for user in users:
            print(f"Shop: {user.username} | Plan: {user.plan_name}")

