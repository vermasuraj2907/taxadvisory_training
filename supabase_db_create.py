import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()
DB_URL = os.getenv('DB_URL')

create_userfinancials_query = '''
CREATE TABLE IF NOT EXISTS UserFinancials (
    session_id UUID PRIMARY KEY,
    gross_salary NUMERIC(15, 2),
    basic_salary NUMERIC(15, 2),
    hra_received NUMERIC(15, 2),
    rent_paid NUMERIC(15, 2),
    deduction_80c NUMERIC(15, 2),
    deduction_80d NUMERIC(15, 2),
    standard_deduction NUMERIC(15, 2),
    professional_tax NUMERIC(15, 2),
    tds NUMERIC(15, 2),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
'''

create_taxcomparison_query = '''
CREATE TABLE IF NOT EXISTS TaxComparison (
    session_id UUID PRIMARY KEY REFERENCES UserFinancials(session_id),
    tax_old_regime NUMERIC(15, 2),
    tax_new_regime NUMERIC(15, 2),
    best_regime VARCHAR(10),
    selected_regime VARCHAR(10),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
'''

def main():
    try:
        conn = psycopg2.connect(DB_URL)
        cur = conn.cursor()
        cur.execute(create_userfinancials_query)
        cur.execute(create_taxcomparison_query)
        conn.commit()
        print('UserFinancials and TaxComparison tables created or already exist.')
        cur.close()
        conn.close()
    except Exception as e:
        print(f'Error: {e}')

if __name__ == '__main__':
    main() 