TAX_CONFIGS = {
    2025: {
        "year": 2025,

        "federal_brackets": [
            (57375.0, 0.145),
            (114750.0, 0.205),
            (177882.0, 0.26),
            (253414.0, 0.29),
            (float("inf"), 0.33),
        ],
        "federal_bpa_max": 16129.0,
        "federal_bpa_min": 14538.0,
        "federal_bpa_phaseout_start": 177882.0,
        "federal_bpa_phaseout_end": 253414.0,
        "canada_employment_amount_max": 1471.0,
        "federal_credit_rate": 0.145,

        "ontario_brackets": [
            (52886.0, 0.0505),
            (105775.0, 0.0915),
            (150000.0, 0.1116),
            (220000.0, 0.1216),
            (float("inf"), 0.1316),
        ],
        "ontario_bpa": 12747.0,
        "ontario_credit_rate": 0.0505,
        "ontario_surtax_first_threshold": 5710.0,
        "ontario_surtax_second_threshold": 7307.0,

        "cpp_ympe": 71300.0,
        "cpp_yampe": 81200.0,
        "cpp_basic_exemption": 3500.0,
        "cpp_max_contributory_earnings": 67800.0,
        "cpp_base_rate": 0.0495,
        "cpp_first_additional_rate": 0.0100,
        "cpp2_rate": 0.0400,
        "ei_max_insurable_earnings": 65700.0,
        "ei_rate": 0.0164,
    },

    2026: {
        "year": 2026,

        "federal_brackets": [
            (58523.0, 0.14),
            (117045.0, 0.205),
            (181440.0, 0.26),
            (258482.0, 0.29),
            (float("inf"), 0.33),
        ],
        "federal_bpa_max": 16452.0,
        "federal_bpa_min": 14829.0,
        "federal_bpa_phaseout_start": 181440.0,
        "federal_bpa_phaseout_end": 258482.0,
        "canada_employment_amount_max": 1501.0,
        "federal_credit_rate": 0.14,

        "ontario_brackets": [
            (53891.0, 0.0505),
            (107785.0, 0.0915),
            (150000.0, 0.1116),
            (220000.0, 0.1216),
            (float("inf"), 0.1316),
        ],
        "ontario_bpa": 12989.0,
        "ontario_credit_rate": 0.0505,
        "ontario_surtax_first_threshold": 5818.0,
        "ontario_surtax_second_threshold": 7446.0,

        "cpp_ympe": 74600.0,
        "cpp_yampe": 85000.0,
        "cpp_basic_exemption": 3500.0,
        "cpp_max_contributory_earnings": 71100.0,
        "cpp_base_rate": 0.0495,
        "cpp_first_additional_rate": 0.0100,
        "cpp2_rate": 0.0400,
        "ei_max_insurable_earnings": 68900.0,
        "ei_rate": 0.0163,
    },
}

AVAILABLE_TAX_YEARS = sorted(TAX_CONFIGS.keys())