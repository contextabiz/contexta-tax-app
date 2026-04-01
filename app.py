import streamlit as st
from tax_config import TAX_CONFIGS, AVAILABLE_TAX_YEARS

import pandas as pd
import altair as alt
import io
import os
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

st.set_page_config(page_title="Ontario Tax Estimator", page_icon="💰")

CURRENT_YEAR = 2026

st.header(
    "Ontario Personal Tax Estimator",
    help="""
Assumptions used in this estimate:

- Ontario resident (full year)
- Employment income only (T4)
- No spouse / dependents
- Basic personal credits only
- No tax credits (tuition, medical, donations, etc.)
- No multiple-job payroll mismatch adjustments
"""
)

DEFAULTS = {
    "tax_year": AVAILABLE_TAX_YEARS[0],
    "employment_income": 60000.0,
    "deductible_contribution": 0.0,
    "rpp_contribution": 0.0,
    "contribution_room_available": 10000.0,
    "use_auto_withheld": True,
    "pay_frequency": "Biweekly (26)",
    "tax_withheld_per_pay": 300.0,
    "annual_tax_withheld": 8000.0,
    "view_mode": "Annual",
    "calculated": False,
}

for key, value in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = value

def reset_form():
    for key, value in DEFAULTS.items():
        st.session_state[key] = value

# -----------------------------
# Input - Tax Year
# -----------------------------
st.subheader("1) Tax Year")

tax_year = st.selectbox(
    "Tax Year",
    AVAILABLE_TAX_YEARS,
    key="tax_year",
    help="Select the tax year you want to estimate. This may be different from the current calendar year."
)

if tax_year < CURRENT_YEAR:
    st.caption("Completed tax year: T4/full-year actual amount is usually the best choice.")
else:
    st.caption("In-progress tax year: per-pay estimate may be useful if you do not yet have a T4.")

# -----------------------------
# Input - Income
# -----------------------------
st.subheader("2) Income")

employment_income = st.number_input(
    "Employment Income",
    min_value=0.0,
    step=1000.0,
    key="employment_income",
)

deductible_contribution = st.number_input(
    "RRSP & FHSA Contribution",
    min_value=0.0,
    step=500.0,
    key="deductible_contribution",
    help="This tool treats RRSP and FHSA contributions as a combined deductible contribution input for simplified planning."
)

rpp_contribution = st.number_input(
    "RPP Contribution",
    min_value=0.0,
    step=500.0,
    key="rpp_contribution",
    help="Registered Pension Plan (RPP) contribution deducted from employment income.",
)

contribution_room_available = st.number_input(
    "Contribution Room Available",
    min_value=0.0,
    step=500.0,
    key="contribution_room_available",
    help="Enter your available RRSP and FHSA contribution room for planning purposes.",
)

st.caption("Contribution room applies to RRSP/FHSA only. RPP is treated separately as a fixed deduction.")

# -----------------------------
# Input - Tax Withheld Method
# -----------------------------
st.subheader("3) Tax Withheld Method")

use_auto_withheld = st.checkbox(
    "Auto-calculate Tax Withheld",
    key="use_auto_withheld",
    help="For most employees, tax is already withheld through payroll. Tick this off if you want to enter the annual amount manually.",
)

tax_withheld = 0.0

pay_periods_map = {
    "Weekly (52)": 52,
    "Biweekly (26)": 26,
    "Semi-monthly (24)": 24,
    "Monthly (12)": 12,
}

if use_auto_withheld:
    pay_frequency = st.selectbox(
        "Pay Frequency",
        list(pay_periods_map.keys()),
        key="pay_frequency",
    )
    tax_withheld_per_pay = st.number_input(
        "Income Tax Withheld Per Pay",
        min_value=0.0,
        step=50.0,
        key="tax_withheld_per_pay",
    )

    pay_periods_per_year = pay_periods_map[pay_frequency]
    tax_withheld = tax_withheld_per_pay * pay_periods_per_year
    st.info(f"Estimated Annual Tax Withheld: ${tax_withheld:,.2f}")
else:
    tax_withheld = st.number_input(
        "Annual Tax Withheld",
        min_value=0.0,
        step=500.0,
        key="annual_tax_withheld",
        help="Example: T4 Box 22, or your own manual estimate for the full year.",
    )


# -----------------------------
# Helper functions
# -----------------------------
def format_currency(amount: float) -> str:
    return f"${amount:,.2f}"


def get_display_divisor(view_mode: str) -> float:
    if view_mode == "Monthly":
        return 12.0
    if view_mode == "Bi-weekly":
        return 26.0
    return 1.0


def format_currency_by_mode(value: float, view_mode: str) -> str:
    if view_mode == "Monthly":
        value = value / 12
    elif view_mode == "Bi-weekly":
        value = value / 26

    if value < 0:
        return f"-${abs(value):,.2f}"
    return f"${value:,.2f}"


def calculate_progressive_tax(income: float, brackets) -> float:
    tax = 0.0
    previous_limit = 0.0

    for limit, rate in brackets:
        if income > previous_limit:
            taxable_amount = min(income, limit) - previous_limit
            tax += taxable_amount * rate
            previous_limit = limit
        else:
            break

    return tax


def get_marginal_rate(income: float, brackets) -> float:
    for limit, rate in brackets:
        if income <= limit:
            return rate
    return brackets[-1][1]


def calculate_federal_bpa(net_income: float, params) -> float:
    max_bpa = params["federal_bpa_max"]
    min_bpa = params["federal_bpa_min"]
    lower_threshold = params["federal_bpa_phaseout_start"]
    upper_threshold = params["federal_bpa_phaseout_end"]

    if net_income <= lower_threshold:
        return max_bpa
    if net_income >= upper_threshold:
        return min_bpa

    reduction_range = max_bpa - min_bpa
    income_range = upper_threshold - lower_threshold
    reduction = ((net_income - lower_threshold) / income_range) * reduction_range
    return max_bpa - reduction


def calculate_canada_employment_amount(employment_income: float, params) -> float:
    return min(params["canada_employment_amount_max"], employment_income)


def estimate_cpp_ei(employment_income: float, params):
    ympe = params["cpp_ympe"]
    yampe = params["cpp_yampe"]
    basic_exemption = params["cpp_basic_exemption"]
    max_contributory_earnings = params["cpp_max_contributory_earnings"]
    max_cpp2_earnings = yampe - ympe
    max_ei_insurable_earnings = params["ei_max_insurable_earnings"]

    cpp_base_rate = params["cpp_base_rate"]
    cpp_first_additional_rate = params["cpp_first_additional_rate"]
    cpp2_rate = params["cpp2_rate"]
    ei_rate = params["ei_rate"]

    contributory_earnings = max(0.0, min(employment_income, ympe) - basic_exemption)
    contributory_earnings = min(contributory_earnings, max_contributory_earnings)

    cpp_base = contributory_earnings * cpp_base_rate
    cpp_first_additional = contributory_earnings * cpp_first_additional_rate

    cpp2_earnings = max(0.0, min(employment_income, yampe) - ympe)
    cpp2_earnings = min(cpp2_earnings, max_cpp2_earnings)
    cpp2 = cpp2_earnings * cpp2_rate

    if employment_income <= 2000:
        ei = 0.0
    else:
        ei = min(employment_income, max_ei_insurable_earnings) * ei_rate

    total_cpp = cpp_base + cpp_first_additional + cpp2
    cpp_enhanced_deduction = cpp_first_additional + cpp2

    return {
        "cpp_base": cpp_base,
        "cpp_first_additional": cpp_first_additional,
        "cpp2": cpp2,
        "total_cpp": total_cpp,
        "ei": ei,
        "cpp_enhanced_deduction": cpp_enhanced_deduction,
    }


def calculate_ontario_surtax(ontario_tax_after_credits: float, params) -> float:
    surtax = 0.0
    first_threshold = params["ontario_surtax_first_threshold"]
    second_threshold = params["ontario_surtax_second_threshold"]

    if ontario_tax_after_credits > first_threshold:
        surtax += (min(ontario_tax_after_credits, second_threshold) - first_threshold) * 0.20

    if ontario_tax_after_credits > second_threshold:
        surtax += (ontario_tax_after_credits - second_threshold) * 0.36

    return max(0.0, surtax)


def calculate_ontario_health_premium(taxable_income: float) -> float:
    income = taxable_income

    if income <= 20000:
        return 0.0
    if income <= 36000:
        return min(300.0, 0.06 * (income - 20000.0))
    if income <= 48000:
        return min(450.0, 300.0 + 0.06 * (income - 36000.0))
    if income <= 72000:
        return min(600.0, 450.0 + 0.25 * (income - 48000.0))
    if income <= 200000:
        return min(750.0, 600.0 + 0.25 * (income - 72000.0))
    return min(900.0, 750.0 + 0.25 * (income - 200000.0))


def get_lower_bracket_target(income: float, brackets):
    """
    Return the upper limit of the next lower bracket for the current income.
    If already in the lowest bracket, return None.
    """
    previous_limit = 0.0

    for limit, rate in brackets:
        if income <= limit:
            if previous_limit == 0.0:
                return None
            return previous_limit
        previous_limit = limit

    return None


def calculate_tax_scenario(
    employment_income: float,
    contribution_used: float,
    rpp_contribution_used: float,
    params,
):
    contributions = estimate_cpp_ei(employment_income, params)

    cpp_base = contributions["cpp_base"]
    cpp_first_additional = contributions["cpp_first_additional"]
    cpp2 = contributions["cpp2"]
    total_cpp = contributions["total_cpp"]
    ei = contributions["ei"]
    cpp_enhanced_deduction = contributions["cpp_enhanced_deduction"]

    net_income = max(
        0.0,
        employment_income
        - rpp_contribution_used
        - contribution_used
        - cpp_enhanced_deduction,
    )
    taxable_income = net_income

    federal_basic_tax = calculate_progressive_tax(
        taxable_income, params["federal_brackets"]
    )
    ontario_basic_tax = calculate_progressive_tax(
        taxable_income, params["ontario_brackets"]
    )

    federal_bpa = calculate_federal_bpa(net_income, params)
    ontario_bpa = params["ontario_bpa"]
    canada_employment_amount = calculate_canada_employment_amount(
        employment_income, params
    )

    federal_credit_rate = params["federal_credit_rate"]
    ontario_credit_rate = params["ontario_credit_rate"]

    federal_bpa_credit = federal_bpa * federal_credit_rate
    federal_cea_credit = canada_employment_amount * federal_credit_rate
    federal_cpp_ei_credit = (cpp_base + ei) * federal_credit_rate

    ontario_bpa_credit = ontario_bpa * ontario_credit_rate
    ontario_cpp_ei_credit = (cpp_base + ei) * ontario_credit_rate

    federal_tax = max(
        0.0,
        federal_basic_tax
        - federal_bpa_credit
        - federal_cea_credit
        - federal_cpp_ei_credit,
    )

    ontario_tax_before_surtax_and_ohp = max(
        0.0,
        ontario_basic_tax
        - ontario_bpa_credit
        - ontario_cpp_ei_credit,
    )

    ontario_surtax = calculate_ontario_surtax(
        ontario_tax_before_surtax_and_ohp, params
    )
    ontario_health_premium = calculate_ontario_health_premium(taxable_income)

    ontario_tax = (
        ontario_tax_before_surtax_and_ohp
        + ontario_surtax
        + ontario_health_premium
    )

    total_tax = federal_tax + ontario_tax

    return {
        "cpp_base": cpp_base,
        "cpp_first_additional": cpp_first_additional,
        "cpp2": cpp2,
        "total_cpp": total_cpp,
        "ei": ei,
        "cpp_enhanced_deduction": cpp_enhanced_deduction,
        "net_income": net_income,
        "taxable_income": taxable_income,
        "federal_basic_tax": federal_basic_tax,
        "ontario_basic_tax": ontario_basic_tax,
        "federal_bpa": federal_bpa,
        "ontario_bpa": ontario_bpa,
        "canada_employment_amount": canada_employment_amount,
        "federal_bpa_credit": federal_bpa_credit,
        "federal_cea_credit": federal_cea_credit,
        "federal_cpp_ei_credit": federal_cpp_ei_credit,
        "ontario_bpa_credit": ontario_bpa_credit,
        "ontario_cpp_ei_credit": ontario_cpp_ei_credit,
        "federal_tax": federal_tax,
        "ontario_tax_before_surtax_and_ohp": ontario_tax_before_surtax_and_ohp,
        "ontario_surtax": ontario_surtax,
        "ontario_health_premium": ontario_health_premium,
        "ontario_tax": ontario_tax,
        "total_tax": total_tax,
    }


def calculate_contribution_bands(
    employment_income: float,
    contribution_used: float,
    optimization_target: float,
    rpp_contribution: float,
    params,
):
    contribution_used = max(0.0, contribution_used)
    optimization_target = max(0.0, optimization_target)

    if contribution_used == 0:
        return []

    base_taxable_income = max(
        0.0,
        employment_income
        - rpp_contribution
        - estimate_cpp_ei(employment_income, params)["cpp_enhanced_deduction"]
    )

    federal_limits = [
        limit for limit, _ in params["federal_brackets"]
        if limit != float("inf")
    ]

    bands = []
    band_starts = [0.0]

    # First band: 0 -> optimization target
    if optimization_target > 0:
        band_starts.append(optimization_target)

    # Then add each federal threshold crossing after optimization target
    for limit in sorted(federal_limits, reverse=True):
        contribution_at_limit = max(0.0, base_taxable_income - limit)
        if optimization_target < contribution_at_limit < contribution_used:
            band_starts.append(contribution_at_limit)

    band_starts = sorted(set(x for x in band_starts if 0.0 <= x <= contribution_used))

    if band_starts[-1] != contribution_used:
        band_starts.append(contribution_used)

    for i in range(len(band_starts) - 1):
        from_contribution = band_starts[i]
        to_contribution = band_starts[i + 1]

        if to_contribution <= from_contribution:
            continue

        tax_before = calculate_tax_scenario(
            employment_income,
            from_contribution,
            rpp_contribution,
            params,
        )["total_tax"]

        tax_after = calculate_tax_scenario(
            employment_income,
            to_contribution,
            rpp_contribution,
            params,
        )["total_tax"]

        tax_saved = tax_before - tax_after
        contribution_amount = to_contribution - from_contribution
        effective_rate = tax_saved / contribution_amount if contribution_amount > 0 else 0.0

        bands.append({
            "from_contribution": from_contribution,
            "to_contribution": to_contribution,
            "tax_saved": tax_saved,
            "effective_rate": effective_rate,
        })

    return bands


def build_tax_curve_data(
    employment_income: float,
    max_contribution: float,
    rpp_contribution: float,
    params,
    step: float = 1000.0,
):
    base_tax = calculate_tax_scenario(
        employment_income,
        0.0,
        rpp_contribution,
        params,
    )["total_tax"]

    curve = []
    contribution = 0.0

    while contribution <= max_contribution:
        scenario = calculate_tax_scenario(
            employment_income,
            contribution,
            rpp_contribution,
            params,
        )

        curve.append({
            "contribution": contribution,
            "tax_saved": base_tax - scenario["total_tax"],
            "total_tax": scenario["total_tax"],
            "taxable_income": scenario["taxable_income"],
        })

        contribution += step

    if not curve or curve[-1]["contribution"] != max_contribution:
        scenario = calculate_tax_scenario(
            employment_income,
            max_contribution,
            rpp_contribution,
            params,
        )
        curve.append({
            "contribution": max_contribution,
            "tax_saved": base_tax - scenario["total_tax"],
            "total_tax": scenario["total_tax"],
            "taxable_income": scenario["taxable_income"],
        })

    return curve


def format_currency_md(value: float) -> str:
    return format_currency(value).replace("$", r"\$")

def safe_currency(x):
    return format_currency(x).replace("$", "\\$")

def generate_pdf_report(
    tax_year: int,
    employment_income: float,
    contribution_used: float,
    rpp_contribution: float,
    taxable_income: float,
    total_tax: float,
    total_cpp: float,
    ei: float,
    net_take_home: float,
    tax_withheld: float,
    difference_display: float,
    suggested_contribution: float,
    total_contribution_tax_saved: float,
):
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    logo_path = "contexta_logo.png"

    if os.path.exists(logo_path):
        p.drawImage(
            logo_path,
            -15,              # x：越細越靠左
            height - 80,     # y：越大越靠上
            width=240,       # logo 顯示闊度
            height=64,       # logo 顯示高度
            preserveAspectRatio=True,
            mask='auto'
        )

    y = height - 100

    def line(text, gap=18, bold=False):
        nonlocal y
        if y < 60:
            p.showPage()
            y = height - 50

        font_name = "Helvetica-Bold" if bold else "Helvetica"
        font_size = 11 if not bold else 12
        p.setFont(font_name, font_size)
        p.drawString(50, y, str(text))
        y -= gap

    p.setTitle("Ontario Tax Estimator Report")

    line("Ontario Tax Estimator Report", gap=24, bold=True)
    line(f"Tax Year: {tax_year}")
    from datetime import datetime
    line(f"Generated on: {datetime.now().strftime('%Y-%m-%d')}")
    line("")

    line("Input Summary", bold=True)
    line(f"Employment Income: {format_currency(employment_income)}")
    line(f"RRSP / FHSA Contribution: {format_currency(contribution_used)}")
    line(f"RPP Contribution: {format_currency(rpp_contribution)}")
    line(f"Tax Withheld: {format_currency(tax_withheld)}")
    line("")

    if difference_display > 0:
        summary = f"You may receive a tax refund of {format_currency(difference_display)}"
    elif difference_display < 0:
        summary = f"You may owe additional tax of {format_currency(abs(difference_display))}"
    else:
        summary = "Your tax withheld is aligned with your estimated tax"

    line("Summary", bold=True)
    line(summary)
    line("")

    line("Estimated Results", bold=True)
    line(f"Taxable Income: {format_currency(taxable_income)}")
    line(f"Total Income Tax: {format_currency(total_tax)}")
    line(f"CPP Contribution: {format_currency(total_cpp)}")
    line(f"EI Premium: {format_currency(ei)}")
    line(f"Net Take-Home: {format_currency(net_take_home)}")
    line("")

    line("Contribution Planning", bold=True)
    line(f"Suggested Contribution Level: {format_currency(suggested_contribution)}")
    line(f"Current Contribution Tax Saved: {format_currency(total_contribution_tax_saved)}")
    line("")

    line("Disclaimer", bold=True)
    line("This is a simplified estimator for employment income scenarios.")
    line("Actual taxes may vary depending on credits, deductions, and CRA rules.")
    line("")
    line("Need a personalized tax or investment strategy?", bold=True)
    line("Contact: info@contexta.biz")

    p.showPage()
    p.save()

    buffer.seek(0)
    return buffer.getvalue()

# -----------------------------
# Calculate
# -----------------------------
calc_col1, calc_col2 = st.columns([1, 1])

with calc_col1:
    calculate_clicked = st.button("Calculate", type="primary")

with calc_col2:
    st.button("Reset", on_click=reset_form)

if calculate_clicked:
    st.session_state.calculated = True

validation_errors = []

if st.session_state.calculated:
    if employment_income <= 0:
        validation_errors.append("Please enter employment income greater than 0.")

    if rpp_contribution > employment_income:
        validation_errors.append("RPP contribution cannot be greater than Employment Income.")

    if deductible_contribution > contribution_room_available:
        validation_errors.append("RRSP / FHSA contribution cannot be greater than available contribution room.")

    if (deductible_contribution + rpp_contribution) > employment_income:
        validation_errors.append("RRSP / FHSA contribution plus RPP contribution cannot be greater than Employment Income.")

if st.session_state.calculated and validation_errors:
    for error in validation_errors:
        st.error(error)
    st.session_state.calculated = False

if st.session_state.calculated:
    params = TAX_CONFIGS[tax_year]

    # ===== Step 1: planning base =====
    contributions = estimate_cpp_ei(employment_income, params)
    cpp_enhanced_deduction = contributions["cpp_enhanced_deduction"]

    planning_net_income = max(
        0.0,
        employment_income - rpp_contribution - deductible_contribution - cpp_enhanced_deduction,
    )
    planning_taxable_income = planning_net_income

    federal_marginal_rate = get_marginal_rate(
        planning_taxable_income, params["federal_brackets"]
    )
    ontario_marginal_rate = get_marginal_rate(
        planning_taxable_income, params["ontario_brackets"]
    )
    combined_marginal_rate = federal_marginal_rate + ontario_marginal_rate

    # ===== Step 2: optimization target contribution =====
    base_taxable_income_for_target = max(
        0.0,
        employment_income - rpp_contribution - cpp_enhanced_deduction,
    )

    lower_bracket_target = get_lower_bracket_target(
        base_taxable_income_for_target, params["federal_brackets"]
    )

    if lower_bracket_target is None:
        suggested_contribution = 0.0
    else:
        raw_suggested_contribution = max(
            0.0,
            base_taxable_income_for_target - lower_bracket_target,
        )
        suggested_contribution = min(
            raw_suggested_contribution,
            contribution_room_available,
        )

    contribution_gap = suggested_contribution - deductible_contribution
    contribution_used = deductible_contribution

    # ===== Step 3: calculate scenarios =====
    scenario_no_contribution = calculate_tax_scenario(
        employment_income,
        0.0,
        rpp_contribution,
        params,
    )
    scenario_current_contribution = calculate_tax_scenario(
        employment_income,
        contribution_used,
        rpp_contribution,
        params,
    )
    scenario_suggested_contribution = calculate_tax_scenario(
        employment_income,
        suggested_contribution,
        rpp_contribution,
        params,
    )

    # Use current scenario as final display scenario
    cpp_base = scenario_current_contribution["cpp_base"]
    cpp_first_additional = scenario_current_contribution["cpp_first_additional"]
    cpp2 = scenario_current_contribution["cpp2"]
    total_cpp = scenario_current_contribution["total_cpp"]
    ei = scenario_current_contribution["ei"]
    cpp_enhanced_deduction = scenario_current_contribution["cpp_enhanced_deduction"]

    net_income = scenario_current_contribution["net_income"]
    taxable_income = scenario_current_contribution["taxable_income"]

    federal_basic_tax = scenario_current_contribution["federal_basic_tax"]
    ontario_basic_tax = scenario_current_contribution["ontario_basic_tax"]
    federal_bpa = scenario_current_contribution["federal_bpa"]
    ontario_bpa = scenario_current_contribution["ontario_bpa"]
    canada_employment_amount = scenario_current_contribution["canada_employment_amount"]
    federal_bpa_credit = scenario_current_contribution["federal_bpa_credit"]
    federal_cea_credit = scenario_current_contribution["federal_cea_credit"]
    federal_cpp_ei_credit = scenario_current_contribution["federal_cpp_ei_credit"]
    ontario_bpa_credit = scenario_current_contribution["ontario_bpa_credit"]
    ontario_cpp_ei_credit = scenario_current_contribution["ontario_cpp_ei_credit"]
    federal_tax = scenario_current_contribution["federal_tax"]
    ontario_tax_before_surtax_and_ohp = scenario_current_contribution[
        "ontario_tax_before_surtax_and_ohp"
    ]
    ontario_surtax = scenario_current_contribution["ontario_surtax"]
    ontario_health_premium = scenario_current_contribution["ontario_health_premium"]
    ontario_tax = scenario_current_contribution["ontario_tax"]
    total_tax = scenario_current_contribution["total_tax"]

    # ===== Step 4: savings and outputs =====
    total_contribution_tax_saved = (
        scenario_no_contribution["total_tax"] - scenario_current_contribution["total_tax"]
    )
    additional_tax_saved_to_optimization = max(
        0.0,
        scenario_current_contribution["total_tax"] - scenario_suggested_contribution["total_tax"],
    )
    progressive_contribution_bands = calculate_contribution_bands(
        employment_income,
        contribution_used,
        suggested_contribution,
        rpp_contribution,
        params,
    )

    tax_curve_data = build_tax_curve_data(
        employment_income,
        contribution_room_available,
        rpp_contribution,
        params,
        step=1000.0,
    )

    difference = tax_withheld - total_tax
    difference_display = round(difference, 2)

    if abs(difference_display) < 0.01:
        difference_display = 0.0

    effective_tax_rate = total_tax / employment_income if employment_income > 0 else 0.0
    net_take_home = (
        employment_income
        - total_tax
        - total_cpp
        - ei
        - rpp_contribution
        - contribution_used
    )
    net_take_home_ratio = net_take_home / employment_income if employment_income > 0 else 0.0
    final_take_home = net_take_home + difference_display

    breakdown_df = pd.DataFrame({
        "Category": ["Tax", "CPP", "EI", "RRSP/FHSA", "RPP", "Take Home"],
        "Amount": [
            total_tax,
            total_cpp,
            ei,
            contribution_used,
            rpp_contribution,
            net_take_home,
        ],
    })

    if employment_income > 0:
        breakdown_df["% of Income"] = breakdown_df["Amount"] / employment_income
    else:
        breakdown_df["% of Income"] = 0.0

    breakdown_df["Category Label"] = breakdown_df.apply(
        lambda row: f"{row['Category']} ({row['% of Income']:.1%})",
        axis=1,
    )

    # -----------------------------
    # Results
    # -----------------------------
    st.subheader("5) Results")

    view_mode = st.radio(
        "View Mode",
        ["Annual", "Monthly", "Bi-weekly"],
        horizontal=True,
        key="view_mode",
        help="Switch between annual, monthly, and bi-weekly display values. Percentages remain the same.",
    )
    display_divisor = get_display_divisor(view_mode)
    view_mode_label = {
        "Annual": "year",
        "Monthly": "month",
        "Bi-weekly": "2 weeks",
    }[view_mode]

    st.markdown("""
    <style>
    .net-takehome-card {
        background: linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%);
        border: 2px solid #10b981;
        border-radius: 16px;
        padding: 22px 24px;
        margin-bottom: 16px;
        box-shadow: 0 4px 14px rgba(16, 185, 129, 0.15);
    }
    .net-takehome-label-row {
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 8px;
    }
    .net-takehome-label {
        font-size: 1rem;
        font-weight: 600;
        color: #065f46;
    }
    .net-takehome-value {
        font-size: 2.4rem;
        font-weight: 800;
        color: #064e3b;
        line-height: 1.1;
    }
    .net-takehome-sub {
        margin-top: 8px;
        font-size: 0.95rem;
        color: #047857;
    }
    .tooltip-icon {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 18px;
        height: 18px;
        border-radius: 50%;
        background: #10b981;
        color: white;
        font-size: 12px;
        font-weight: 700;
        cursor: help;
        position: relative;
    }
    .tooltip-icon::after {
        content: attr(data-tooltip);
        position: absolute;
        bottom: 130%;
        left: 50%;
        transform: translateX(-50%);
        background: #064e3b;
        color: white;
        padding: 8px 10px;
        border-radius: 8px;
        font-size: 0.8rem;
        font-weight: 400;
        line-height: 1.3;
        white-space: nowrap;
        opacity: 0;
        pointer-events: none;
        transition: opacity 0.2s ease;
        z-index: 999;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    }
    .tooltip-icon:hover::after {
        opacity: 1;
    }
    </style>
    """, unsafe_allow_html=True)

    st.markdown(
        f"""
        <div class="net-takehome-card">
            <div class="net-takehome-label-row">
                <div class="net-takehome-label">Net Take-Home</div>
                <div class="tooltip-icon" data-tooltip="Net Take-Home = Employment Income − Tax − CPP − EI − RRSP/FHSA − RPP">?</div>
            </div>
            <div class="net-takehome-value">{format_currency_by_mode(net_take_home, view_mode)}</div>
            <div class="net-takehome-sub">
                {net_take_home_ratio:.2%} of Employment Income
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    takehome_col1, takehome_col2 = st.columns(2)

    takehome_col1.metric(
        "Tax Refund / Owing",
        format_currency_by_mode(difference_display, view_mode),
    )

    takehome_col2.metric(
        "Final Take-Home",
        format_currency_by_mode(final_take_home, view_mode),
    )

    if difference_display > 0:
        st.success(
            "You may receive a tax refund because more tax was withheld than required."
        )
    
    elif difference_display < 0:
        message = (
            f"You may owe additional tax because less tax was withheld "
            f"({safe_currency(tax_withheld)}) than required "
            f"({safe_currency(total_tax)})."
        )
        st.warning(message)
    
    else:
        st.info(
            "Your tax withheld matches your estimated total tax, so you may have no refund or balance owing."
        )

    with st.expander("Income Breakdown"):
        st.write(
            f"Tax Year: {tax_year}  |  Employment Income: {format_currency_by_mode(employment_income, view_mode)}"
        )
        st.caption(
            f"This chart shows how your employment income is allocated on a {view_mode.lower()} basis."
        )

        display_breakdown_df = breakdown_df.copy()
        display_breakdown_df["Amount"] = display_breakdown_df["Amount"] / display_divisor
        total_income_display = display_breakdown_df["Amount"].sum()

        color_scale = alt.Scale(
            domain=breakdown_df["Category Label"].tolist(),
            range=[
                "#C62828",  # Tax
                "#1565C0",  # CPP
                "#6A1B9A",  # EI
                "#F9A825",  # RRSP/FHSA
                "#00838F",  # RPP
                "#16A34A",  # Take Home
            ],
        )

        hover = alt.selection_point(
            fields=["Category Label"],
            on="mouseover",
            clear="mouseout"
        )

        donut_chart = (
            alt.Chart(display_breakdown_df)
            .mark_arc(innerRadius=80, outerRadius=140)
            .encode(
                theta=alt.Theta("Amount:Q"),
                color=alt.Color(
                    "Category Label:N",
                    scale=color_scale,
                    title="Category",
                    legend=alt.Legend(orient="right")
                ),
                opacity=alt.condition(hover, alt.value(1.0), alt.value(0.75)),
                strokeWidth=alt.condition(hover, alt.value(3), alt.value(1)),
                tooltip=[
                    alt.Tooltip("Category:N", title="Category"),
                    alt.Tooltip("Amount:Q", title=f"Amount per {view_mode_label}", format="$,.2f"),
                    alt.Tooltip("% of Income:Q", title="% of Income", format=".2%"),
                ],
                order=alt.Order("Amount:Q", sort="descending"),
            )
            .add_params(hover)
            .properties(height=350)
        )

        take_home_amount_display = display_breakdown_df.loc[
            display_breakdown_df["Category"] == "Take Home", "Amount"
        ].values[0]

        take_home_ratio_display = (
            take_home_amount_display / total_income_display
            if total_income_display > 0 else 0.0
        )

        center_value = alt.Chart(
            pd.DataFrame({"text": [format_currency_by_mode(net_take_home, view_mode)]})
        ).mark_text(
            size=28,
            fontWeight="bold",
            color="#16A34A",
            dy=-20,
        ).encode(
            text="text:N"
        )

        center_label = alt.Chart(
            pd.DataFrame({"text": ["Net Take-Home"]})
        ).mark_text(
            size=14,
            color="#166534",
            dy=6,
        ).encode(
            text="text:N"
        )

        insight = alt.Chart(
            pd.DataFrame({
                "text": [f"Take-Home Ratio: {take_home_ratio_display:.1%}"]
            })
        ).mark_text(
            size=12,
            color="#9CA3AF",
            dy=24,
        ).encode(
            text="text:N"
        )

        final_chart = alt.layer(
            donut_chart,
            center_value,
            center_label,
            insight,
        ).configure_view(
            stroke=None
        )

        st.altair_chart(final_chart, use_container_width=True)

    # -----------------------------
    # Contribution Optimization & Scenario Comparison
    # -----------------------------
    st.markdown("---")
    st.markdown(
        "### RRSP & FHSA Contribution Optimization",
        help=(
            "This contribution optimization target is based on reducing your taxable "
            "income to the next lower federal tax bracket. It is a simplified estimate "
            "and does not consider provincial surtax or other factors."
            " RPP is treated separately as a fixed deduction."
        ),
    )

    contribution_col1, contribution_col2, contribution_col3 = st.columns(3)

    contribution_col1.metric("Current Contribution", format_currency_by_mode(deductible_contribution, view_mode))

    if suggested_contribution == 0:
        contribution_col2.metric("Contribution Gap", format_currency_by_mode(0.0, view_mode))
        contribution_col3.metric("Total Tax Saved", format_currency_by_mode(total_contribution_tax_saved, view_mode))
        st.info(
            f"No additional contribution is suggested to reach a lower federal tax bracket. "
            f"Your current contribution is saving you "
            f"{format_currency(total_contribution_tax_saved)} in tax compared with making no contribution."
        )

    elif contribution_gap > 0:
        contribution_col2.metric("Contribution Gap", format_currency_by_mode(contribution_gap, view_mode))
        contribution_col3.metric(
            "Potential Extra Tax Savings",
            format_currency_by_mode(additional_tax_saved_to_optimization, view_mode),
        )
        st.warning(
            f"You are already saving {format_currency_md(total_contribution_tax_saved)} in tax.\n\n"
            f"Increase by {format_currency_md(contribution_gap)} to reach the suggested level and "
            f"save about {format_currency_md(additional_tax_saved_to_optimization)} more."
        )

    elif contribution_gap < 0:
        contribution_col2.metric("Amount Above Target", format_currency_by_mode(abs(contribution_gap), view_mode))
        contribution_col3.metric("Total Tax Saved", format_currency_by_mode(total_contribution_tax_saved, view_mode))
        st.info(
            f"You are already saving {format_currency(total_contribution_tax_saved)} in tax "
            f"compared with making no contribution.\n\n"
            f"Your current contribution may have exceeded the most tax-efficient level, "
            f"where additional contributions provide diminishing tax benefits."
        )

    else:
        contribution_col2.metric("Contribution Gap", format_currency_by_mode(0.0, view_mode))
        contribution_col3.metric("Total Tax Saved", format_currency_by_mode(total_contribution_tax_saved, view_mode))
        st.success(
            f"You are already saving {format_currency(total_contribution_tax_saved)} in tax "
            f"compared with making no contribution.\n\n"
            f"Your contribution is already at the most tax-efficient contribution level. "
        )

    st.markdown(
        "#### RRSP & FHSA Contribution vs Tax Savings",
        help=(
            "This chart shows estimated tax saved compared with making no contribution."
        ),
    )

    CURRENT_COLOR = "#22D3EE"
    SUGGESTED_COLOR = "#F59E0B"

    curve_df = pd.DataFrame(tax_curve_data)
    display_curve_df = curve_df.copy()
    display_curve_df["contribution"] = display_curve_df["contribution"] / display_divisor
    display_curve_df["tax_saved"] = display_curve_df["tax_saved"] / display_divisor
    display_curve_df["total_tax"] = display_curve_df["total_tax"] / display_divisor
    display_curve_df["taxable_income"] = display_curve_df["taxable_income"] / display_divisor

    top_y = display_curve_df["tax_saved"].max() if not display_curve_df.empty else 0
    label_y = top_y * 1.08 if top_y > 0 else 0

    line = alt.Chart(display_curve_df).mark_line(color="#94A3B8", strokeWidth=3).encode(
        x=alt.X("contribution:Q", title=f"Contribution ({view_mode})"),
        y=alt.Y(
            "tax_saved:Q",
            title=f"Estimated Tax Saved ({view_mode})",
            scale=alt.Scale(zero=True),
        ),
        tooltip=[
            alt.Tooltip("contribution:Q", title=f"Contribution per {view_mode_label}", format=",.0f"),
            alt.Tooltip("tax_saved:Q", title=f"Tax Saved per {view_mode_label}", format=",.0f"),
            alt.Tooltip("total_tax:Q", title=f"Total Tax per {view_mode_label}", format=",.0f"),
            alt.Tooltip("taxable_income:Q", title=f"Taxable Income per {view_mode_label}", format=",.0f"),
        ],
    )

    current_rule_df = pd.DataFrame({
        "x": [contribution_used / display_divisor],
        "label": ["Current"],
    })

    target_rule_df = pd.DataFrame({
        "x": [suggested_contribution / display_divisor],
        "label": ["Suggested"],
    })

    current_rule = alt.Chart(current_rule_df).mark_rule(
        color=CURRENT_COLOR,
        strokeWidth=2,
        strokeDash=[6, 4],
    ).encode(
        x="x:Q",
        tooltip=[
            alt.Tooltip("label:N", title="Marker"),
            alt.Tooltip("x:Q", title=f"Contribution per {view_mode_label}", format=",.0f"),
        ],
    )

    target_rule = alt.Chart(target_rule_df).mark_rule(
        color=SUGGESTED_COLOR,
        strokeWidth=2,
        strokeDash=[6, 4],
    ).encode(
        x="x:Q",
        tooltip=[
            alt.Tooltip("label:N", title="Marker"),
            alt.Tooltip("x:Q", title=f"Contribution per {view_mode_label}", format=",.0f"),
        ],
    )

    current_text = alt.Chart(pd.DataFrame({
        "x": [contribution_used / display_divisor],
        "y": [label_y],
        "label": ["Current"],
    })).mark_text(
        align="left",
        dx=6,
        dy=-6,
        color=CURRENT_COLOR,
        fontSize=13,
        fontWeight="bold",
    ).encode(
        x="x:Q",
        y="y:Q",
        text="label:N",
    )

    target_text = alt.Chart(pd.DataFrame({
        "x": [suggested_contribution / display_divisor],
        "y": [label_y],
        "label": ["Suggested"],
    })).mark_text(
        align="left",
        dx=6,
        dy=14,
        color=SUGGESTED_COLOR,
        fontSize=13,
        fontWeight="bold",
    ).encode(
        x="x:Q",
        y="y:Q",
        text="label:N",
    )

    current_point_df = pd.DataFrame({
        "contribution": [contribution_used / display_divisor],
        "tax_saved": [(scenario_no_contribution["total_tax"] - scenario_current_contribution["total_tax"]) / display_divisor],
        "label": ["Current"],
    })

    target_point_df = pd.DataFrame({
        "contribution": [suggested_contribution / display_divisor],
        "tax_saved": [(scenario_no_contribution["total_tax"] - scenario_suggested_contribution["total_tax"]) / display_divisor],
        "label": ["Suggested"],
    })

    current_point = alt.Chart(current_point_df).mark_circle(
        size=140,
        color=CURRENT_COLOR,
        stroke="white",
        strokeWidth=2,
    ).encode(
        x=alt.X("contribution:Q"),
        y=alt.Y("tax_saved:Q"),
        tooltip=[
            alt.Tooltip("label:N", title="Point"),
            alt.Tooltip("contribution:Q", title=f"Contribution per {view_mode_label}", format=",.0f"),
            alt.Tooltip("tax_saved:Q", title=f"Tax Saved per {view_mode_label}", format=",.0f"),
        ],
    )

    target_point = alt.Chart(target_point_df).mark_circle(
        size=140,
        color=SUGGESTED_COLOR,
        stroke="white",
        strokeWidth=2,
    ).encode(
        x=alt.X("contribution:Q"),
        y=alt.Y("tax_saved:Q"),
        tooltip=[
            alt.Tooltip("label:N", title="Point"),
            alt.Tooltip("contribution:Q", title=f"Contribution per {view_mode_label}", format=",.0f"),
            alt.Tooltip("tax_saved:Q", title=f"Tax Saved per {view_mode_label}", format=",.0f"),
        ],
    )

    chart = (
        line
        + current_rule
        + target_rule
        + current_text
        + target_text
        + current_point
        + target_point
    ).properties(height=360)

    st.altair_chart(chart, use_container_width=True)

    st.markdown("#### Compare Plans")
    st.caption("Amounts shown are estimated total income tax payable.")

    col1, col2, col3 = st.columns(3)
    col1.metric("Your Current Plan", format_currency_by_mode(scenario_current_contribution["total_tax"], view_mode))
    col1.caption(f"Contribution = {format_currency_by_mode(contribution_used, view_mode)}")

    col2.metric("No Contribution", format_currency_by_mode(scenario_no_contribution["total_tax"], view_mode))
    col2.caption(f"Contribution = {format_currency_by_mode(0.0, view_mode)}")

    col3.metric("Suggested Plan", format_currency_by_mode(scenario_suggested_contribution["total_tax"], view_mode))
    col3.caption(f"Contribution = {format_currency_by_mode(suggested_contribution, view_mode)}")

    with st.expander("Progressive Contribution Saving"):
        if contribution_used == 0:
            st.info("Set a current contribution above $0 to compare bands from your current level.")
        else:
            band_rows = []

            for i, band in enumerate(progressive_contribution_bands):
                from_amt = band["from_contribution"] / display_divisor
                to_amt = band["to_contribution"] / display_divisor
                tax_saved_amt = band["tax_saved"] / display_divisor

                if i == 0 and suggested_contribution > 0:
                    band_label = f"0 to Suggested Contribution ({format_currency(to_amt)})"
                else:
                    band_label = f"{format_currency(from_amt)} - {format_currency(to_amt)}"

                band_rows.append({
                    "Contribution Band": band_label,
                    f"Tax Saved ({view_mode})": format_currency(tax_saved_amt),
                    "Effective Saving Rate": f"{band['effective_rate']:.2%}",
                })

            band_df = pd.DataFrame(band_rows)
            st.dataframe(band_df, use_container_width=True, hide_index=True)

    # -----------------------------
    # Advanced Breakdown
    # -----------------------------
    st.markdown("---")
    with st.expander("Advanced Breakdown"):

        if difference_display >= 0:
            refund_label = "Estimated Refund"
        else:
            refund_label = "Estimated Amount Owing"

        summary_rows = [
            {"Item": "Employment Income", "Amount": employment_income},
            {"Item": "Less: RRSP / FHSA Deduction", "Amount": -contribution_used},
            {"Item": "Less: RPP Contribution", "Amount": -rpp_contribution},
            {"Item": "Less: CPP Enhanced Deduction", "Amount": -cpp_enhanced_deduction},
            {"Item": "Taxable Income", "Amount": taxable_income, "highlight": True},
            {"Item": "Less: Federal Tax", "Amount": -federal_tax},
            {"Item": "Less: Ontario Tax", "Amount": -ontario_tax},
            {"Item": "Less: CPP Contribution", "Amount": -total_cpp},
            {"Item": "Less: EI Premium", "Amount": -ei},
            {"Item": "Add: CPP Enhanced Deduction", "Amount": cpp_enhanced_deduction},
            {"Item": "Net Take-Home", "Amount": net_take_home, "highlight": True},
            {"Item": "", "Amount": None},
            {"Item": "Total Estimated Tax", "Amount": total_tax},
            {"Item": "Income Tax Withheld", "Amount": tax_withheld},
            {"Item": refund_label, "Amount": abs(difference_display)},
            {"Item": "Ontario Surtax", "Amount": ontario_surtax},
            {"Item": "Ontario Health Premium", "Amount": ontario_health_premium},
        ]

        st.markdown("#### Calculation Summary")

        for row in summary_rows:
            item = row["Item"]
            amount = row["Amount"]

            if amount is None:
                st.markdown("---")
                continue

            formatted_amount = format_currency_by_mode(amount, view_mode)

            if row.get("highlight"):
                icon = "💡" if item == "Taxable Income" else "💰"
                st.markdown(f"**{icon} {item}: {formatted_amount}**")
            else:
                st.write(f"{item}: {formatted_amount}")

        # 放 CTA 喺呢度
        st.markdown("---")

        st.info(
            """
        📊 Want a deeper strategy and breakdown?
        📧 Reach out anytime: **info@contexta.biz**
        """
        )

        st.markdown("---")
        st.markdown("#### Tax Rates")
        rate_col1, rate_col2 = st.columns(2)
        rate_col1.metric("Effective Tax Rate", f"{effective_tax_rate:.2%}")
        rate_col2.metric("Marginal Tax Rate", f"{combined_marginal_rate:.2%}")

        st.markdown("---")
        st.markdown("#### Tax Breakdown")

        federal_col, ontario_col = st.columns(2)

        with federal_col:
            st.markdown("##### Federal")
            st.metric("Estimated Federal Tax", format_currency_by_mode(federal_tax, view_mode))

            with st.expander("Show Federal Details"):
                st.write(f"Federal Basic Tax: {format_currency_by_mode(federal_basic_tax, view_mode)}")
                st.write(f"Federal Basic Personal Amount: {format_currency_by_mode(federal_bpa, view_mode)}")
                st.write(f"Federal BPA Credit: {format_currency_by_mode(federal_bpa_credit, view_mode)}")
                st.write(
                    f"Canada Employment Amount: {format_currency_by_mode(canada_employment_amount, view_mode)}"
                )
                st.write(f"Federal CEA Credit: {format_currency_by_mode(federal_cea_credit, view_mode)}")
                st.write(
                    f"Federal CPP/EI Credit: {format_currency_by_mode(federal_cpp_ei_credit, view_mode)}"
                )

        with ontario_col:
            st.markdown("##### Ontario")
            st.metric("Estimated Ontario Tax", format_currency_by_mode(ontario_tax, view_mode))

            with st.expander("Show Ontario Details"):
                st.write(f"Ontario Basic Tax: {format_currency_by_mode(ontario_basic_tax, view_mode)}")
                st.write(f"Ontario Basic Personal Amount: {format_currency_by_mode(ontario_bpa, view_mode)}")
                st.write(f"Ontario BPA Credit: {format_currency_by_mode(ontario_bpa_credit, view_mode)}")
                st.write(f"Ontario CPP/EI Credit: {format_currency_by_mode(ontario_cpp_ei_credit, view_mode)}")
                st.write(
                    "Ontario Tax Before Surtax & Health Premium: "
                    f"{format_currency_by_mode(ontario_tax_before_surtax_and_ohp, view_mode)}"
                )
                st.write(f"Ontario Surtax: {format_currency_by_mode(ontario_surtax, view_mode)}")
                st.write(
                    f"Ontario Health Premium: {format_currency_by_mode(ontario_health_premium, view_mode)}"
                )

        st.markdown("---")

        st.markdown("#### CPP / EI Estimate")

        cpp_col1, cpp_col2, cpp_col3 = st.columns(3)
        cpp_col1.metric("Total CPP", format_currency_by_mode(total_cpp, view_mode))
        cpp_col2.metric("EI Premium", format_currency_by_mode(ei, view_mode))
        cpp_col3.metric("CPP Enhanced Deduction", format_currency_by_mode(cpp_enhanced_deduction, view_mode))

        with st.expander("Show CPP / EI Details"):
            st.write(f"CPP Base Contribution: {format_currency_by_mode(cpp_base, view_mode)}")
            st.write(f"CPP First Additional: {format_currency_by_mode(cpp_first_additional, view_mode)}")
            st.write(f"CPP2: {format_currency_by_mode(cpp2, view_mode)}")
            st.write(f"Total CPP: {format_currency_by_mode(total_cpp, view_mode)}")
            st.write(f"EI Premium: {format_currency_by_mode(ei, view_mode)}")

        pdf_bytes = generate_pdf_report(
            tax_year=tax_year,
            employment_income=employment_income,
            contribution_used=contribution_used,
            rpp_contribution=rpp_contribution,
            taxable_income=taxable_income,
            total_tax=total_tax,
            total_cpp=total_cpp,
            ei=ei,
            net_take_home=net_take_home,
            tax_withheld=tax_withheld,
            difference_display=difference_display,
            suggested_contribution=suggested_contribution,
            total_contribution_tax_saved=total_contribution_tax_saved,
        )

        st.download_button(
            label="Download PDF Report",
            data=pdf_bytes,
            file_name=f"ontario_tax_estimate_{tax_year}.pdf",
            mime="application/pdf",
            type="primary",
        )

st.markdown("---")
st.caption(
    "This is a simplified estimator designed for employment income scenarios. While generally accurate for straightforward cases, "
    "actual taxes may vary depending on additional credits, deductions, and CRA rules."
)
