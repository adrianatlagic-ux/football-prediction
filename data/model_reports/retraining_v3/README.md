# Club retraining comparison

Selected on development: `verified_only/monthly/raw`.

| Season | Competition | Strategy | n | Accuracy | Log loss | Brier |
|---|---|---|---:|---:|---:|---:|
| 2021-22 | bundesliga | lagged_season/frozen/calibrated | 306 | 51.0% | 1.0059 | 0.5992 |
| 2021-22 | bundesliga | lagged_season/frozen/raw | 306 | 51.0% | 1.0064 | 0.5990 |
| 2021-22 | bundesliga | verified_only/frozen/calibrated | 306 | 50.3% | 1.0178 | 0.6082 |
| 2021-22 | bundesliga | verified_only/frozen/raw | 306 | 50.3% | 1.0169 | 0.6073 |
| 2021-22 | bundesliga | verified_only/monthly/calibrated | 306 | 48.7% | 1.0271 | 0.6130 |
| 2021-22 | bundesliga | verified_only/monthly/raw | 306 | 48.7% | 1.0257 | 0.6121 |
| 2021-22 | champions_league | lagged_season/frozen/calibrated | 125 | 53.6% | 0.9744 | 0.5814 |
| 2021-22 | champions_league | lagged_season/frozen/raw | 125 | 53.6% | 0.9674 | 0.5773 |
| 2021-22 | champions_league | verified_only/frozen/calibrated | 125 | 55.2% | 0.9634 | 0.5737 |
| 2021-22 | champions_league | verified_only/frozen/raw | 125 | 55.2% | 0.9590 | 0.5711 |
| 2021-22 | champions_league | verified_only/monthly/calibrated | 125 | 56.0% | 0.9672 | 0.5758 |
| 2021-22 | champions_league | verified_only/monthly/raw | 125 | 56.0% | 0.9607 | 0.5721 |
| 2022-23 | bundesliga | lagged_season/frozen/calibrated | 306 | 53.9% | 1.0142 | 0.6066 |
| 2022-23 | bundesliga | lagged_season/frozen/raw | 306 | 53.9% | 1.0140 | 0.6066 |
| 2022-23 | bundesliga | verified_only/frozen/calibrated | 306 | 52.6% | 1.0171 | 0.6066 |
| 2022-23 | bundesliga | verified_only/frozen/raw | 306 | 52.6% | 1.0173 | 0.6072 |
| 2022-23 | bundesliga | verified_only/monthly/calibrated | 306 | 52.3% | 1.0151 | 0.6061 |
| 2022-23 | bundesliga | verified_only/monthly/raw | 306 | 52.3% | 1.0115 | 0.6041 |
| 2022-23 | champions_league | lagged_season/frozen/calibrated | 125 | 58.4% | 0.9387 | 0.5514 |
| 2022-23 | champions_league | lagged_season/frozen/raw | 125 | 58.4% | 0.9402 | 0.5526 |
| 2022-23 | champions_league | verified_only/frozen/calibrated | 125 | 60.0% | 0.9269 | 0.5444 |
| 2022-23 | champions_league | verified_only/frozen/raw | 125 | 60.0% | 0.9308 | 0.5473 |
| 2022-23 | champions_league | verified_only/monthly/calibrated | 125 | 57.6% | 0.9219 | 0.5411 |
| 2022-23 | champions_league | verified_only/monthly/raw | 125 | 57.6% | 0.9252 | 0.5436 |
| 2023-24 | bundesliga | lagged_season/frozen/calibrated | 306 | 51.0% | 0.9883 | 0.5875 |
| 2023-24 | bundesliga | lagged_season/frozen/raw | 306 | 51.0% | 0.9889 | 0.5879 |
| 2023-24 | bundesliga | verified_only/frozen/calibrated | 306 | 53.9% | 0.9882 | 0.5865 |
| 2023-24 | bundesliga | verified_only/frozen/raw | 306 | 53.9% | 0.9897 | 0.5877 |
| 2023-24 | bundesliga | verified_only/monthly/calibrated | 306 | 53.9% | 0.9871 | 0.5839 |
| 2023-24 | bundesliga | verified_only/monthly/raw | 306 | 53.9% | 0.9874 | 0.5855 |
| 2023-24 | champions_league | lagged_season/frozen/calibrated | 125 | 50.4% | 0.9986 | 0.5953 |
| 2023-24 | champions_league | lagged_season/frozen/raw | 125 | 50.4% | 0.9984 | 0.5952 |
| 2023-24 | champions_league | verified_only/frozen/calibrated | 125 | 48.8% | 0.9980 | 0.5946 |
| 2023-24 | champions_league | verified_only/frozen/raw | 125 | 48.8% | 0.9977 | 0.5945 |
| 2023-24 | champions_league | verified_only/monthly/calibrated | 125 | 52.8% | 0.9990 | 0.5941 |
| 2023-24 | champions_league | verified_only/monthly/raw | 125 | 52.8% | 0.9926 | 0.5908 |
| 2025-26 | bundesliga | lagged_season/frozen/calibrated | 306 | 54.6% | 0.9735 | 0.5765 |
| 2025-26 | bundesliga | lagged_season/frozen/raw | 306 | 54.6% | 0.9741 | 0.5771 |
| 2025-26 | bundesliga | verified_only/frozen/calibrated | 306 | 53.9% | 0.9870 | 0.5870 |
| 2025-26 | bundesliga | verified_only/frozen/raw | 306 | 53.9% | 0.9876 | 0.5875 |
| 2025-26 | bundesliga | verified_only/monthly/calibrated | 306 | 53.6% | 0.9894 | 0.5876 |
| 2025-26 | bundesliga | verified_only/monthly/raw | 306 | 53.6% | 0.9866 | 0.5862 |
| 2025-26 | champions_league | lagged_season/frozen/calibrated | 189 | 53.4% | 0.9768 | 0.5824 |
| 2025-26 | champions_league | lagged_season/frozen/raw | 189 | 53.4% | 0.9775 | 0.5828 |
| 2025-26 | champions_league | verified_only/frozen/calibrated | 189 | 52.4% | 0.9815 | 0.5847 |
| 2025-26 | champions_league | verified_only/frozen/raw | 189 | 52.4% | 0.9823 | 0.5851 |
| 2025-26 | champions_league | verified_only/monthly/calibrated | 189 | 51.3% | 0.9826 | 0.5846 |
| 2025-26 | champions_league | verified_only/monthly/raw | 189 | 51.3% | 0.9778 | 0.5820 |

No betting profitability claim: historical pre-match odds are absent.
2025/26 has already been used in earlier experiments. Lagged season values are an unverified sensitivity analysis.
