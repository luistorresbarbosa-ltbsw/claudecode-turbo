"""Preços: o custo calculado tem de bater com o que o Claude Code reporta."""
import pytest

from jev import pricing

# usage real de `claude -p --model haiku --effort low "responde so: ok"` (claude 2.1.287, 2026-10-11)
HAIKU_PROBE_USAGE = {
    "input_tokens": 10,
    "cache_creation_input_tokens": 9683,
    "cache_read_input_tokens": 13803,
    "output_tokens": 392,
    "output_tokens_details": {"thinking_tokens": 385},
    "cache_creation": {"ephemeral_1h_input_tokens": 9683, "ephemeral_5m_input_tokens": 0},
}
HAIKU_PROBE_TOTAL_COST_USD = 0.0227163  # o total_cost_usd reportado nessa execução


def test_haiku_cost_matches_what_claude_code_reported():
    tokens = pricing.tokens_from_claude_usage(HAIKU_PROBE_USAGE)

    assert pricing.cost_of("claude-haiku-4-5-20251001", tokens) == pytest.approx(HAIKU_PROBE_TOTAL_COST_USD)


def test_usage_splits_cache_writes_by_ttl():
    assert pricing.tokens_from_claude_usage(HAIKU_PROBE_USAGE) == {
        "input": 10, "output": 392, "cache_read": 13803, "cache_write_5m": 0, "cache_write_1h": 9683,
    }


def test_usage_without_ttl_breakdown_counts_cache_writes_as_1h():
    usage = {"input_tokens": 1, "output_tokens": 2, "cache_read_input_tokens": 3,
             "cache_creation_input_tokens": 400}

    assert pricing.tokens_from_claude_usage(usage)["cache_write_1h"] == 400


@pytest.mark.parametrize("model, usd_per_m_output", [
    ("haiku", 5.0), ("sonnet", 10.0), ("opus", 20.0), ("fable", 50.0),
])
def test_cli_aliases_price_as_the_current_models(model, usd_per_m_output):
    assert pricing.cost_of(model, {"output": 1_000_000}) == pytest.approx(usd_per_m_output)


def test_sonnet_5_5_cache_reads_use_the_official_price_not_litellms():
    # litellm 1.104 traz $0.10/M; o preço oficial (skill claude-api, 2026-09-25) é $0.20/M
    assert pricing.cost_of("sonnet", {"cache_read": 1_000_000}) == pytest.approx(0.20)


def test_one_hour_cache_writes_cost_twice_the_input_price():
    assert pricing.cost_of("opus", {"cache_write_1h": 1_000_000}) == pytest.approx(8.0)
    assert pricing.cost_of("opus", {"cache_write_5m": 1_000_000}) == pytest.approx(5.0)


def test_free_openrouter_models_cost_nothing():
    tokens = {"input": 1_000_000, "output": 1_000_000}

    assert pricing.cost_of("nvidia/nemotron-3-super-120b-a12b:free", tokens) == 0.0


def test_unknown_model_is_an_error_not_a_free_ride():
    with pytest.raises(KeyError):
        pricing.cost_of("claude-inventado-9", {"output": 1})


def test_with_cc_overhead_adds_claude_codes_fixed_context():
    tokens = pricing.with_cc_overhead({"input": 1000, "output": 500})

    # 1000×$4 + 500×$20 + 13803×$0.20 + 9683×$8, tudo por milhão (preços Opus 5.5)
    assert pricing.cost_of("opus", tokens) == pytest.approx(0.0942246)


def test_sonnet_cost_matches_what_claude_code_reported():
    # usage real de `claude -p --model sonnet --effort low` (claude 2.1.287, 2026-10-11): total_cost_usd 0.0592396
    usage = {"input_tokens": 2, "output_tokens": 4, "cache_read_input_tokens": 10738,
             "cache_creation_input_tokens": 14262,
             "cache_creation": {"ephemeral_1h_input_tokens": 14262, "ephemeral_5m_input_tokens": 0}}

    assert pricing.cost_of("claude-sonnet-5-5", pricing.tokens_from_claude_usage(usage)) == pytest.approx(0.0592396)
