# Strategy Test Matrix Report

本报告由 `scripts/ops/strategy_test_matrix_runner.py` 生成。只读 replay samples，不写生产数据库，不发交易。

## Datasets
- sr_chainstack_highres_strategy: {'sampleCount': 1034, 'firstTimestamp': 1776049216, 'lastTimestamp': 1776055153, 'durationSec': 5937, 'taxMin': '1', 'taxMax': '99', 'boardSpentMaxV': '315347.598'}
- sr_chainstack_full-20260507T080007Z: {'sampleCount': 144, 'firstTimestamp': 1776049217, 'lastTimestamp': 1776055153, 'durationSec': 5936, 'taxMin': '1', 'taxMax': '99', 'boardSpentMaxV': '314740.058'}
- isc_chainstack_suite-20260507T073928Z: {'sampleCount': 113, 'firstTimestamp': 1777473004, 'lastTimestamp': 1777473604, 'durationSec': 600, 'taxMin': '89', 'taxMax': '99', 'boardSpentMaxV': '43919.553'}
- tds_chainstack_full-20260507T075130Z: {'sampleCount': 144, 'firstTimestamp': 1777555804, 'lastTimestamp': 1777561742, 'durationSec': 5938, 'taxMin': '1', 'taxMax': '97', 'boardSpentMaxV': '29821.722'}

## Summary
- ruleCount: 737
- scenarioCount: 34
- resultCount: 4136

## Report Notes
- `Top By Risk Adjusted Score` excludes critical-risk cases such as no FDV guard, no board-spent guard, low-sample first buy, high latency, high slippage, or tax-signal anomalies.
- `Reject List` means rejected as a direct dry-run / trading candidate. Some rejected controls can still be useful as ablation evidence.
- `Dry-run Candidates` only includes actual-scenario candidates with positive final PnL and no low-sample first buy.

## Suite Summary
| Suite | Count | Triggered | Positive | Positive Rate | Median PnL % | Min PnL % | Max PnL % |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ablation | 44 | 30 | 26 | 0.8667 | 35.0952 | -91.9558 | 60.5536 |
| combo_burst_x_cooldown | 84 | 42 | 42 | 1.0 | 40.4541 | 37.5114 | 41.1205 |
| combo_cooldown_x_max_spend | 168 | 84 | 84 | 1.0 | 40.4541 | 38.0501 | 41.1205 |
| combo_min_rows_x_spent | 224 | 96 | 96 | 1.0 | 39.2521 | 38.0501 | 40.4541 |
| combo_spent_x_fdv | 192 | 72 | 72 | 1.0 | 40.4541 | 9.0354 | 40.5818 |
| combo_spent_x_tax | 504 | 258 | 228 | 0.8837 | 40.4541 | -90.7099 | 104.4073 |
| combo_spent_x_tax_no_fdv | 504 | 300 | 258 | 0.86 | 9.4219 | -91.9558 | 60.5536 |
| combo_spent_x_tax_x_fdv | 768 | 342 | 342 | 1.0 | 40.4541 | 37.5757 | 83.8259 |
| combo_tax_x_fdv | 144 | 129 | 93 | 0.7209 | 26.0021 | -91.9558 | 118.1326 |
| control | 272 | 259 | 180 | 0.695 | 26.0021 | -95.9779 | 160.6444 |
| dry_run_candidates | 952 | 422 | 388 | 0.9194 | 40.4541 | -89.749 | 134.0304 |
| single_burst_gradient | 12 | 6 | 6 | 1.0 | 39.5361 | 38.0501 | 40.4541 |
| single_cooldown_gradient | 28 | 14 | 14 | 1.0 | 40.4541 | 38.0501 | 41.1205 |
| single_fdv_discount_gradient | 24 | 9 | 9 | 1.0 | 40.4541 | 9.0354 | 40.5818 |
| single_max_spend_gradient | 24 | 12 | 12 | 1.0 | 40.4541 | 38.0501 | 41.1205 |
| single_min_rows_gradient | 28 | 12 | 12 | 1.0 | 39.2521 | 38.0501 | 40.4541 |
| single_spent_gradient | 84 | 43 | 38 | 0.8837 | 38.0501 | -89.6651 | 40.4541 |
| single_tax_gradient | 80 | 21 | 21 | 1.0 | 40.0431 | 33.7736 | 40.4541 |

## Top By Final Return
| Dataset | Suite | Rule | Scenario | Buys | Spent V | PnL % | Score | First Buy | Risk Flags |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| sr_chainstack_highres_strategy | control | control_tax95_fdv_no_spent | price_up_50pct | 2 | 100 | 160.6444 | 136.7411 | tax 95, board 8193.431, fdv 315.78535, cost 535.732007 | no_board_spent_guard, early_board_spent |
| sr_chainstack_full-20260507T080007Z | control | control_tax95_fdv_no_spent | price_up_50pct | 2 | 100 | 158.4477 | 134.2149 | tax 95, board 8393.431, fdv 322.440875, cost 545.964709 | no_board_spent_guard, early_board_spent |
| tds_chainstack_full-20260507T075130Z | control | control_tax_only_95 | price_up_50pct | 6 | 300 | 134.237 | 145.4894 | tax 27, board 0, fdv 1.864098, cost None | no_fdv_cost_guard, no_board_spent_guard, low_sample_first_buy, early_board_spent |
| sr_chainstack_highres_strategy | dry_run_candidates | aggressive_50k_tax95_fdv | price_up_50pct | 2 | 100 | 134.0304 | 107.135 | tax 93, board 54966.025, fdv 285.005894, cost 331.375072 |  |
| sr_chainstack_highres_strategy | dry_run_candidates | aggressive_50k_tax94_fdv | price_up_50pct | 2 | 100 | 134.0304 | 107.135 | tax 93, board 54966.025, fdv 285.005894, cost 331.375072 |  |
| sr_chainstack_highres_strategy | dry_run_candidates | aggressive_50k_tax93_fdv | price_up_50pct | 2 | 100 | 134.0304 | 107.135 | tax 93, board 54966.025, fdv 285.005894, cost 331.375072 |  |
| sr_chainstack_highres_strategy | combo_tax_x_fdv | tax<=93\|fdv=0.95 | actual | 1 | 50 | 118.1326 | 89.1025 | tax 93, board 21210.792, fdv 232.714603, cost 409.266034 | no_board_spent_guard, early_board_spent |
| sr_chainstack_highres_strategy | combo_tax_x_fdv | tax<=93\|fdv=0.9 | actual | 1 | 50 | 118.1326 | 89.1025 | tax 93, board 21210.792, fdv 232.714603, cost 409.266034 | no_board_spent_guard, early_board_spent |
| sr_chainstack_full-20260507T080007Z | combo_tax_x_fdv | tax<=93\|fdv=0.9 | actual | 1 | 50 | 117.1772 | 88.0038 | tax 93, board 22065.792, fdv 238.419731, cost 411.880739 | no_board_spent_guard, early_board_spent |
| sr_chainstack_highres_strategy | control | control_tax95_fdv_no_spent | fast_rebound | 2 | 100 | 110.1169 | 78.6344 | tax 95, board 8193.431, fdv 260.135807, cost 535.732007 | no_board_spent_guard, early_board_spent |
| sr_chainstack_full-20260507T080007Z | control | control_tax95_fdv_no_spent | fast_rebound | 2 | 100 | 107.9363 | 76.1267 | tax 95, board 8393.431, fdv 265.807506, cost 545.964709 | no_board_spent_guard, early_board_spent |
| sr_chainstack_highres_strategy | combo_spent_x_tax | spent=0\|tax<=94\|fdv | actual | 2 | 100 | 104.4073 | 72.5684 | tax 94, board 16014.212, fdv 265.043376, cost 456.145018 | early_board_spent |
| sr_chainstack_highres_strategy | combo_spent_x_tax | spent=10000\|tax<=94\|fdv | actual | 2 | 100 | 104.4073 | 72.5684 | tax 94, board 16014.212, fdv 265.043376, cost 456.145018 | early_board_spent |
| sr_chainstack_highres_strategy | combo_tax_x_fdv | tax<=94\|fdv=1 | actual | 2 | 100 | 104.4073 | 72.5684 | tax 94, board 16014.212, fdv 265.043376, cost 456.145018 | no_board_spent_guard, early_board_spent |
| sr_chainstack_highres_strategy | combo_tax_x_fdv | tax<=94\|fdv=0.99 | actual | 2 | 100 | 104.4073 | 72.5684 | tax 94, board 16014.212, fdv 265.043376, cost 456.145018 | no_board_spent_guard, early_board_spent |
| sr_chainstack_highres_strategy | combo_tax_x_fdv | tax<=94\|fdv=0.98 | actual | 2 | 100 | 104.4073 | 72.5684 | tax 94, board 16014.212, fdv 265.043376, cost 456.145018 | no_board_spent_guard, early_board_spent |
| sr_chainstack_highres_strategy | combo_tax_x_fdv | tax<=94\|fdv=0.95 | actual | 2 | 100 | 104.4073 | 72.5684 | tax 94, board 16014.212, fdv 265.043376, cost 456.145018 | no_board_spent_guard, early_board_spent |
| sr_chainstack_highres_strategy | combo_tax_x_fdv | tax<=94\|fdv=0.9 | actual | 2 | 100 | 104.4073 | 72.5684 | tax 94, board 16014.212, fdv 265.043376, cost 456.145018 | no_board_spent_guard, early_board_spent |
| sr_chainstack_highres_strategy | control | control_tax95_fdv_no_spent | delay_60s | 2 | 100 | 104.4073 | 72.5684 | tax 95, board 8193.431, fdv 265.043376, cost 535.732007 | no_board_spent_guard, high_latency, early_board_spent |
| sr_chainstack_full-20260507T080007Z | dry_run_candidates | conservative_100k_tax92_fdv | price_up_50pct | 1 | 50 | 101.5315 | 71.5112 | tax 90, board 164791.135, fdv 385.393797, cost 388.266344 |  |

## Top By Risk Adjusted Score
| Dataset | Suite | Rule | Scenario | Buys | Spent V | PnL % | Score | First Buy | Risk Flags |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| sr_chainstack_highres_strategy | dry_run_candidates | aggressive_50k_tax95_fdv | price_up_50pct | 2 | 100 | 134.0304 | 107.135 | tax 93, board 54966.025, fdv 285.005894, cost 331.375072 |  |
| sr_chainstack_highres_strategy | dry_run_candidates | aggressive_50k_tax94_fdv | price_up_50pct | 2 | 100 | 134.0304 | 107.135 | tax 93, board 54966.025, fdv 285.005894, cost 331.375072 |  |
| sr_chainstack_highres_strategy | dry_run_candidates | aggressive_50k_tax93_fdv | price_up_50pct | 2 | 100 | 134.0304 | 107.135 | tax 93, board 54966.025, fdv 285.005894, cost 331.375072 |  |
| sr_chainstack_highres_strategy | combo_spent_x_tax | spent=0\|tax<=94\|fdv | actual | 2 | 100 | 104.4073 | 72.5684 | tax 94, board 16014.212, fdv 265.043376, cost 456.145018 | early_board_spent |
| sr_chainstack_highres_strategy | combo_spent_x_tax | spent=10000\|tax<=94\|fdv | actual | 2 | 100 | 104.4073 | 72.5684 | tax 94, board 16014.212, fdv 265.043376, cost 456.145018 | early_board_spent |
| sr_chainstack_full-20260507T080007Z | dry_run_candidates | conservative_100k_tax92_fdv | price_up_50pct | 1 | 50 | 101.5315 | 71.5112 | tax 90, board 164791.135, fdv 385.393797, cost 388.266344 |  |
| sr_chainstack_full-20260507T080007Z | dry_run_candidates | mid_70k_tax95_fdv | price_up_50pct | 1 | 50 | 101.5315 | 71.5112 | tax 90, board 164791.135, fdv 385.393797, cost 388.266344 |  |
| sr_chainstack_full-20260507T080007Z | dry_run_candidates | mid_80k_tax95_fdv | price_up_50pct | 1 | 50 | 101.5315 | 71.5112 | tax 90, board 164791.135, fdv 385.393797, cost 388.266344 |  |
| sr_chainstack_full-20260507T080007Z | dry_run_candidates | mid_90k_tax95_fdv | price_up_50pct | 1 | 50 | 101.5315 | 71.5112 | tax 90, board 164791.135, fdv 385.393797, cost 388.266344 |  |
| sr_chainstack_full-20260507T080007Z | dry_run_candidates | aggressive_50k_tax95_fdv | price_up_50pct | 1 | 50 | 101.5315 | 71.5112 | tax 90, board 164791.135, fdv 385.393797, cost 388.266344 |  |
| sr_chainstack_full-20260507T080007Z | dry_run_candidates | aggressive_50k_tax94_fdv | price_up_50pct | 1 | 50 | 101.5315 | 71.5112 | tax 90, board 164791.135, fdv 385.393797, cost 388.266344 |  |
| sr_chainstack_full-20260507T080007Z | dry_run_candidates | aggressive_50k_tax93_fdv | price_up_50pct | 1 | 50 | 101.5315 | 71.5112 | tax 90, board 164791.135, fdv 385.393797, cost 388.266344 |  |
| sr_chainstack_highres_strategy | dry_run_candidates | conservative_100k_tax92_fdv | price_up_50pct | 1 | 50 | 100.8946 | 70.7788 | tax 90, board 164791.135, fdv 379.024493, cost 380.642784 |  |
| sr_chainstack_highres_strategy | dry_run_candidates | mid_70k_tax95_fdv | price_up_50pct | 1 | 50 | 100.8946 | 70.7788 | tax 90, board 164791.135, fdv 379.024493, cost 380.642784 |  |
| sr_chainstack_highres_strategy | dry_run_candidates | mid_80k_tax95_fdv | price_up_50pct | 1 | 50 | 100.8946 | 70.7788 | tax 90, board 164791.135, fdv 379.024493, cost 380.642784 |  |
| sr_chainstack_highres_strategy | dry_run_candidates | mid_90k_tax95_fdv | price_up_50pct | 1 | 50 | 100.8946 | 70.7788 | tax 90, board 164791.135, fdv 379.024493, cost 380.642784 |  |
| sr_chainstack_full-20260507T080007Z | combo_spent_x_tax | spent=10000\|tax<=95\|fdv | actual | 2 | 100 | 88.6131 | 53.9051 | tax 95, board 15214.212, fdv 323.521709, cost 468.953468 | early_board_spent |
| sr_chainstack_highres_strategy | combo_spent_x_tax_x_fdv | spent=50000\|tax<=95\|fdv=0.95 | actual | 1 | 50 | 83.8259 | 49.6498 | tax 93, board 54966.025, fdv 276.145245, cost 331.375072 |  |
| sr_chainstack_highres_strategy | combo_spent_x_tax_x_fdv | spent=50000\|tax<=94\|fdv=0.95 | actual | 1 | 50 | 83.8259 | 49.6498 | tax 93, board 54966.025, fdv 276.145245, cost 331.375072 |  |
| sr_chainstack_highres_strategy | combo_spent_x_tax_x_fdv | spent=50000\|tax<=93\|fdv=0.95 | actual | 1 | 50 | 83.8259 | 49.6498 | tax 93, board 54966.025, fdv 276.145245, cost 331.375072 |  |

## Stable Zone
| Suite | Triggered | Positive Rate | Median PnL % | Min PnL % | Max PnL % |
| --- | ---: | ---: | ---: | ---: | ---: |
| combo_burst_x_cooldown | 42 | 1.0 | 40.4541 | 37.5114 | 41.1205 |
| combo_cooldown_x_max_spend | 84 | 1.0 | 40.4541 | 38.0501 | 41.1205 |
| combo_spent_x_fdv | 72 | 1.0 | 40.4541 | 9.0354 | 40.5818 |
| combo_spent_x_tax_x_fdv | 342 | 1.0 | 40.4541 | 37.5757 | 83.8259 |
| single_cooldown_gradient | 14 | 1.0 | 40.4541 | 38.0501 | 41.1205 |
| single_fdv_discount_gradient | 9 | 1.0 | 40.4541 | 9.0354 | 40.5818 |
| single_max_spend_gradient | 12 | 1.0 | 40.4541 | 38.0501 | 41.1205 |
| single_tax_gradient | 21 | 1.0 | 40.0431 | 33.7736 | 40.4541 |
| single_burst_gradient | 6 | 1.0 | 39.5361 | 38.0501 | 40.4541 |
| combo_min_rows_x_spent | 96 | 1.0 | 39.2521 | 38.0501 | 40.4541 |
| single_min_rows_gradient | 12 | 1.0 | 39.2521 | 38.0501 | 40.4541 |

## Failure Cases
| Dataset | Suite | Rule | Scenario | Buys | Spent V | PnL % | Score | First Buy | Risk Flags |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| isc_chainstack_suite-20260507T073928Z | control | control_tax_only_95 | late_dump_50pct | 2 | 100 | -95.9779 | -158.7773 | tax 95, board 0.1, fdv 250.761058, cost 417.935035 | no_fdv_cost_guard, no_board_spent_guard, low_sample_first_buy, early_board_spent |
| isc_chainstack_suite-20260507T073928Z | control | control_tax95_fdv_no_spent | late_dump_50pct | 2 | 100 | -95.3238 | -157.6326 | tax 94, board 1740.786, fdv 210.618877, cost 275.172824 | no_board_spent_guard, early_board_spent |
| isc_chainstack_suite-20260507T073928Z | control | control_tax_only_95 | tax_offset_minus2 | 2 | 100 | -94.859 | -158.0879 | tax 95, board 0, fdv 417.934973, cost None | no_fdv_cost_guard, no_board_spent_guard, low_sample_first_buy, tax_signal_risk, early_board_spent |
| isc_chainstack_suite-20260507T073928Z | control | control_tax_only_95 | early_pump_flat | 2 | 100 | -94.0884 | -156.3516 | tax 95, board 0.1, fdv 350.508235, cost 417.935035 | no_fdv_cost_guard, no_board_spent_guard, low_sample_first_buy, early_board_spent |
| isc_chainstack_suite-20260507T073928Z | control | control_tax_only_95 | price_down_30pct | 2 | 100 | -93.4709 | -155.5561 | tax 95, board 0.1, fdv 220.41897, cost 417.935035 | no_fdv_cost_guard, no_board_spent_guard, low_sample_first_buy, early_board_spent |
| isc_chainstack_suite-20260507T073928Z | control | control_tax_only_95 | slippage_10pct | 2 | 100 | -92.6871 | -154.8175 | tax 95, board 0.1, fdv 275.837164, cost 417.935035 | no_fdv_cost_guard, no_board_spent_guard, low_sample_first_buy, high_slippage, early_board_spent |
| isc_chainstack_suite-20260507T073928Z | control | control_tax_only_95 | slippage_5pct | 2 | 100 | -92.3389 | -154.3088 | tax 95, board 0.1, fdv 263.299111, cost 417.935035 | no_fdv_cost_guard, no_board_spent_guard, low_sample_first_buy, high_slippage, early_board_spent |
| isc_chainstack_suite-20260507T073928Z | control | control_tax_only_95 | slippage_3pct | 2 | 100 | -92.1901 | -154.0915 | tax 95, board 0.1, fdv 258.28389, cost 417.935035 | no_fdv_cost_guard, no_board_spent_guard, low_sample_first_buy, early_board_spent |
| isc_chainstack_suite-20260507T073928Z | control | control_tax95_fdv_no_spent | price_down_30pct | 2 | 100 | -92.1815 | -153.5069 | tax 94, board 1740.786, fdv 178.815426, cost 275.172824 | no_board_spent_guard, early_board_spent |
| isc_chainstack_suite-20260507T073928Z | control | control_tax_only_95 | delay_30s | 2 | 100 | -92.1134 | -153.9304 | tax 95, board 0.1, fdv 251.497451, cost 417.935035 | no_fdv_cost_guard, no_board_spent_guard, low_sample_first_buy, high_latency, early_board_spent |
| isc_chainstack_suite-20260507T073928Z | control | control_tax_only_95 | entry_delay_30s | 2 | 100 | -92.1121 | -153.9289 | tax 95, board 0.1, fdv 251.497451, cost 417.935035 | no_fdv_cost_guard, no_board_spent_guard, low_sample_first_buy, high_latency, early_board_spent |
| isc_chainstack_suite-20260507T073928Z | control | control_tax_only_95 | sample_30s | 2 | 100 | -92.1039 | -153.9194 | tax 95, board 740.686, fdv 251.497351, cost 313.921718 | no_fdv_cost_guard, no_board_spent_guard, low_sample_first_buy, early_board_spent |
| isc_chainstack_suite-20260507T073928Z | control | control_tax_only_95 | entry_delay_12s | 2 | 100 | -92.077 | -153.8885 | tax 95, board 0.1, fdv 251.497351, cost 417.935035 | no_fdv_cost_guard, no_board_spent_guard, low_sample_first_buy, early_board_spent |
| isc_chainstack_suite-20260507T073928Z | control | control_tax_only_95 | delay_6s | 2 | 100 | -92.0537 | -153.8617 | tax 95, board 0.1, fdv 251.497351, cost 417.935035 | no_fdv_cost_guard, no_board_spent_guard, low_sample_first_buy, early_board_spent |
| isc_chainstack_suite-20260507T073928Z | control | control_tax_only_95 | sample_15s | 2 | 100 | -92.0429 | -153.8494 | tax 95, board 0.1, fdv 250.761058, cost 417.935035 | no_fdv_cost_guard, no_board_spent_guard, low_sample_first_buy, early_board_spent |
| isc_chainstack_suite-20260507T073928Z | control | control_tax_only_95 | buy_failure_every_3 | 2 | 100 | -92.0429 | -153.8494 | tax 95, board 0.1, fdv 250.761058, cost 417.935035 | no_fdv_cost_guard, no_board_spent_guard, low_sample_first_buy, early_board_spent |
| isc_chainstack_suite-20260507T073928Z | control | control_tax_only_95 | slippage_1pct | 2 | 100 | -92.0355 | -153.8656 | tax 95, board 0.1, fdv 253.268669, cost 417.935035 | no_fdv_cost_guard, no_board_spent_guard, low_sample_first_buy, early_board_spent |
| isc_chainstack_suite-20260507T073928Z | control | control_tax_only_95 | slippage_0_5pct | 2 | 100 | -91.9959 | -153.8077 | tax 95, board 0.1, fdv 252.014864, cost 417.935035 | no_fdv_cost_guard, no_board_spent_guard, low_sample_first_buy, early_board_spent |
| isc_chainstack_suite-20260507T073928Z | ablation | only_tax95 | actual | 2 | 100 | -91.9558 | -153.7492 | tax 95, board 0.1, fdv 250.761058, cost 417.935035 | no_fdv_cost_guard, no_board_spent_guard, low_sample_first_buy, early_board_spent |
| isc_chainstack_suite-20260507T073928Z | combo_spent_x_tax_no_fdv | spent=0\|tax<=95\|no_fdv | actual | 2 | 100 | -91.9558 | -153.7492 | tax 95, board 0.1, fdv 250.761058, cost 417.935035 | no_fdv_cost_guard, low_sample_first_buy, early_board_spent |

## Dry-run Candidates
| Dataset | Suite | Rule | Scenario | Buys | Spent V | PnL % | Score | First Buy | Risk Flags |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| sr_chainstack_highres_strategy | dry_run_candidates | conservative_100k_tax92_fdv | actual | 2 | 100 | 38.0501 | -2.7424 | tax 92, board 132032.472, fdv 359.711454, cost 364.638858 |  |
| sr_chainstack_highres_strategy | dry_run_candidates | mid_70k_tax95_fdv | actual | 2 | 100 | 42.1103 | 1.4268 | tax 93, board 98430.254, fdv 340.432566, cost 341.684717 |  |
| sr_chainstack_highres_strategy | dry_run_candidates | mid_80k_tax95_fdv | actual | 2 | 100 | 42.1103 | 1.4268 | tax 93, board 98430.254, fdv 340.432566, cost 341.684717 |  |
| sr_chainstack_highres_strategy | dry_run_candidates | mid_90k_tax95_fdv | actual | 2 | 100 | 42.1103 | 1.4268 | tax 93, board 98430.254, fdv 340.432566, cost 341.684717 |  |
| sr_chainstack_highres_strategy | dry_run_candidates | aggressive_50k_tax95_fdv | actual | 2 | 100 | 59.4671 | 21.3872 | tax 93, board 54966.025, fdv 276.145245, cost 331.375072 |  |
| sr_chainstack_highres_strategy | dry_run_candidates | aggressive_50k_tax94_fdv | actual | 2 | 100 | 59.4671 | 21.3872 | tax 93, board 54966.025, fdv 276.145245, cost 331.375072 |  |
| sr_chainstack_highres_strategy | dry_run_candidates | aggressive_50k_tax93_fdv | actual | 2 | 100 | 59.4671 | 21.3872 | tax 93, board 54966.025, fdv 276.145245, cost 331.375072 |  |
| sr_chainstack_full-20260507T080007Z | dry_run_candidates | conservative_100k_tax92_fdv | actual | 1 | 50 | 40.4541 | 1.2723 | tax 90, board 164791.135, fdv 368.656447, cost 388.266344 |  |
| sr_chainstack_full-20260507T080007Z | dry_run_candidates | mid_70k_tax95_fdv | actual | 1 | 50 | 40.4541 | 1.2723 | tax 90, board 164791.135, fdv 368.656447, cost 388.266344 |  |
| sr_chainstack_full-20260507T080007Z | dry_run_candidates | mid_80k_tax95_fdv | actual | 1 | 50 | 40.4541 | 1.2723 | tax 90, board 164791.135, fdv 368.656447, cost 388.266344 |  |
| sr_chainstack_full-20260507T080007Z | dry_run_candidates | mid_90k_tax95_fdv | actual | 1 | 50 | 40.4541 | 1.2723 | tax 90, board 164791.135, fdv 368.656447, cost 388.266344 |  |
| sr_chainstack_full-20260507T080007Z | dry_run_candidates | aggressive_50k_tax95_fdv | actual | 1 | 50 | 40.4541 | 1.2723 | tax 90, board 164791.135, fdv 368.656447, cost 388.266344 |  |
| sr_chainstack_full-20260507T080007Z | dry_run_candidates | aggressive_50k_tax94_fdv | actual | 1 | 50 | 40.4541 | 1.2723 | tax 90, board 164791.135, fdv 368.656447, cost 388.266344 |  |
| sr_chainstack_full-20260507T080007Z | dry_run_candidates | aggressive_50k_tax93_fdv | actual | 1 | 50 | 40.4541 | 1.2723 | tax 90, board 164791.135, fdv 368.656447, cost 388.266344 |  |

## Reject List
| Dataset | Suite | Rule | Scenario | Buys | Spent V | PnL % | Score | First Buy | Risk Flags |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| sr_chainstack_highres_strategy | single_fdv_discount_gradient | spent=100k\|tax<=92\|fdv=none | actual | 6 | 300 | 12.441 | -33.1929 | tax 92, board 132032.472, fdv 359.711454, cost 364.638858 | no_fdv_cost_guard |
| sr_chainstack_highres_strategy | ablation | only_tax92 | actual | 6 | 300 | 12.441 | -33.1929 | tax 92, board 132032.472, fdv 359.711454, cost 364.638858 | no_fdv_cost_guard, no_board_spent_guard |
| sr_chainstack_highres_strategy | ablation | only_tax95 | actual | 6 | 300 | 28.6425 | -16.0611 | tax 95, board 8193.431, fdv 309.529078, cost 535.732007 | no_fdv_cost_guard, no_board_spent_guard, early_board_spent |
| sr_chainstack_highres_strategy | ablation | only_spent100k | actual | 6 | 300 | 9.3104 | -37.2931 | tax 93, board 107986.039, fdv 360.469682, cost 347.432283 | no_fdv_cost_guard, no_tax_guard |
| sr_chainstack_highres_strategy | ablation | only_fdv | actual | 2 | 100 | 32.1403 | -12.0387 | tax 97, board 1054.854, fdv 506.204055, cost 796.376585 | no_board_spent_guard, no_tax_guard, early_board_spent |
| sr_chainstack_highres_strategy | ablation | spent100k_plus_tax92 | actual | 6 | 300 | 12.441 | -33.1929 | tax 92, board 132032.472, fdv 359.711454, cost 364.638858 | no_fdv_cost_guard |
| sr_chainstack_highres_strategy | ablation | tax92_plus_fdv | actual | 2 | 100 | 38.0501 | -2.7424 | tax 92, board 132032.472, fdv 359.711454, cost 364.638858 | no_board_spent_guard |
| sr_chainstack_highres_strategy | combo_spent_x_tax_no_fdv | spent=0\|tax<=95\|no_fdv | actual | 6 | 300 | 28.6425 | -16.0611 | tax 95, board 8193.431, fdv 309.529078, cost 535.732007 | no_fdv_cost_guard, early_board_spent |
| sr_chainstack_highres_strategy | combo_spent_x_tax_no_fdv | spent=0\|tax<=94\|no_fdv | actual | 6 | 300 | 36.5159 | -6.5068 | tax 94, board 16014.212, fdv 265.043376, cost 456.145018 | no_fdv_cost_guard, early_board_spent |
| sr_chainstack_highres_strategy | combo_spent_x_tax_no_fdv | spent=0\|tax<=93\|no_fdv | actual | 6 | 300 | 28.268 | -15.4918 | tax 93, board 21210.792, fdv 232.714603, cost 409.266034 | no_fdv_cost_guard, early_board_spent |
| sr_chainstack_highres_strategy | combo_spent_x_tax_no_fdv | spent=0\|tax<=92\|no_fdv | actual | 6 | 300 | 12.441 | -33.1929 | tax 92, board 132032.472, fdv 359.711454, cost 364.638858 | no_fdv_cost_guard |
| sr_chainstack_highres_strategy | combo_spent_x_tax_no_fdv | spent=0\|tax<=91\|no_fdv | actual | 6 | 300 | 13.0862 | -31.9509 | tax 91, board 159224.769, fdv 375.718035, cost 377.853186 | no_fdv_cost_guard |
| sr_chainstack_highres_strategy | combo_spent_x_tax_no_fdv | spent=0\|tax<=90\|no_fdv | actual | 6 | 300 | 11.1551 | -33.6716 | tax 90, board 164791.135, fdv 362.478804, cost 380.642784 | no_fdv_cost_guard |
| sr_chainstack_highres_strategy | combo_spent_x_tax_no_fdv | spent=10000\|tax<=95\|no_fdv | actual | 6 | 300 | 23.7924 | -21.6388 | tax 95, board 13513.431, fdv 315.295862, cost 469.388305 | no_fdv_cost_guard, early_board_spent |
| sr_chainstack_highres_strategy | combo_spent_x_tax_no_fdv | spent=10000\|tax<=94\|no_fdv | actual | 6 | 300 | 36.5159 | -6.5068 | tax 94, board 16014.212, fdv 265.043376, cost 456.145018 | no_fdv_cost_guard, early_board_spent |
| sr_chainstack_highres_strategy | combo_spent_x_tax_no_fdv | spent=10000\|tax<=93\|no_fdv | actual | 6 | 300 | 28.268 | -15.4918 | tax 93, board 21210.792, fdv 232.714603, cost 409.266034 | no_fdv_cost_guard, early_board_spent |
| sr_chainstack_highres_strategy | combo_spent_x_tax_no_fdv | spent=10000\|tax<=92\|no_fdv | actual | 6 | 300 | 12.441 | -33.1929 | tax 92, board 132032.472, fdv 359.711454, cost 364.638858 | no_fdv_cost_guard |
| sr_chainstack_highres_strategy | combo_spent_x_tax_no_fdv | spent=10000\|tax<=91\|no_fdv | actual | 6 | 300 | 13.0862 | -31.9509 | tax 91, board 159224.769, fdv 375.718035, cost 377.853186 | no_fdv_cost_guard |
| sr_chainstack_highres_strategy | combo_spent_x_tax_no_fdv | spent=10000\|tax<=90\|no_fdv | actual | 6 | 300 | 11.1551 | -33.6716 | tax 90, board 164791.135, fdv 362.478804, cost 380.642784 | no_fdv_cost_guard |
| sr_chainstack_highres_strategy | combo_spent_x_tax_no_fdv | spent=20000\|tax<=95\|no_fdv | actual | 6 | 300 | 28.268 | -15.4918 | tax 93, board 21210.792, fdv 232.714603, cost 409.266034 | no_fdv_cost_guard, early_board_spent |

## Variable Contribution
| Rule | PnL % | Delta vs Baseline | Buy Count | Risk Flags |
| --- | ---: | ---: | ---: | --- |
| only_tax92 | 12.441 | -25.6091 | 6 | no_fdv_cost_guard, no_board_spent_guard |
| only_tax95 | 28.6425 | -9.4076 | 6 | no_fdv_cost_guard, no_board_spent_guard, early_board_spent |
| only_spent100k | 9.3104 | -28.7397 | 6 | no_fdv_cost_guard, no_tax_guard |
| only_fdv | 32.1403 | -5.9098 | 2 | no_board_spent_guard, no_tax_guard, early_board_spent |
| spent100k_plus_tax92 | 12.441 | -25.6091 | 6 | no_fdv_cost_guard |
| spent100k_plus_fdv | 38.0501 | 0.0 | 2 | no_tax_guard |
| tax92_plus_fdv | 38.0501 | 0.0 | 2 | no_board_spent_guard |
| cancel_cooldown | 40.6187 | 2.5686 | 2 |  |
| cancel_max_spend | 38.0501 | 0.0 | 2 | large_project_budget |
| cancel_min_rows | 38.0501 | 0.0 | 2 |  |

## Overfit Warnings
- Some high-return cases trigger with boardSpentV below 50k; treat as early-sample risk.
- Tax-only or no-FDV-cost cases often buy more exposure; they are controls, not trade candidates.
