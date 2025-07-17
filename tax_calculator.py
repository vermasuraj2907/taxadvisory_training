def calculate_tax_old_regime(data):
    # Extract values, default to 0 if missing
    gross_salary = float(data.get('gross_salary', 0) or 0)
    basic_salary = float(data.get('basic_salary', 0) or 0)
    hra_received = float(data.get('hra_received', 0) or 0)
    rent_paid = float(data.get('rent_paid', 0) or 0)
    deduction_80c = float(data.get('deduction_80c', 0) or 0)
    deduction_80d = float(data.get('deduction_80d', 0) or 0)
    standard_deduction = float(data.get('standard_deduction', 50000) or 50000)
    professional_tax = float(data.get('professional_tax', 0) or 0)
    tds = float(data.get('tds', 0) or 0)

    # Deductions
    total_deductions = standard_deduction + hra_received + professional_tax + deduction_80c + deduction_80d
    taxable_income = max(gross_salary - total_deductions, 0)

    # Old regime slabs
    tax = 0
    if taxable_income > 250000:
        if taxable_income <= 500000:
            tax = 0.05 * (taxable_income - 250000)
        elif taxable_income <= 1000000:
            tax = 0.05 * 250000 + 0.2 * (taxable_income - 500000)
        else:
            tax = 0.05 * 250000 + 0.2 * 500000 + 0.3 * (taxable_income - 1000000)
    # 4% cess
    tax_with_cess = tax * 1.04
    return round(tax_with_cess, 2)

def calculate_tax_new_regime(data):
    gross_salary = float(data.get('gross_salary', 0) or 0)
    standard_deduction = float(data.get('standard_deduction', 50000) or 50000)
    taxable_income = max(gross_salary - standard_deduction, 0)

    # New regime slabs
    tax = 0
    if taxable_income > 300000:
        if taxable_income <= 600000:
            tax = 0.05 * (taxable_income - 300000)
        elif taxable_income <= 900000:
            tax = 0.05 * 300000 + 0.1 * (taxable_income - 600000)
        elif taxable_income <= 1200000:
            tax = 0.05 * 300000 + 0.1 * 300000 + 0.15 * (taxable_income - 900000)
        elif taxable_income <= 1500000:
            tax = 0.05 * 300000 + 0.1 * 300000 + 0.15 * 300000 + 0.2 * (taxable_income - 1200000)
        else:
            tax = 0.05 * 300000 + 0.1 * 300000 + 0.15 * 300000 + 0.2 * 300000 + 0.3 * (taxable_income - 1500000)
    # 4% cess
    tax_with_cess = tax * 1.04
    return round(tax_with_cess, 2) 