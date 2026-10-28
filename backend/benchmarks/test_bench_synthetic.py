from sensebench.synthetic import generate


def test_generate_1h_run(within_budget):
    within_budget(generate, 3600.0, 100, 0)
