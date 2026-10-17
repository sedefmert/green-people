# Analysis summary

Runs analysed: 100 (all runs incl. invalid: 101; invalid: 1)

## Omnibus tests (BH-adjusted)

| hypothesis       | metric   | column                 | effect            | method                                        |        F |      p |   p_bh |   partial_eta2 | reject_H0   |
|:-----------------|:---------|:-----------------------|:------------------|:----------------------------------------------|---------:|-------:|-------:|---------------:|:------------|
| H1.1             | M1       | cpu_util_mean_compress | treatment         | ART ANOVA                                     | 159.385  | 0      | 0      |         0.8691 | True        |
| H1.2             | M1       | cpu_util_mean_compress | treatment:payload | ART ANOVA                                     |   0.0505 | 0.9849 | 0.9849 |         0.0021 | False       |
| H1.1             | M1       | cpu_util_mean_transmit | treatment         | two-way ANOVA on sqrt(cpu_util_mean_transmit) |  21.8389 | 0      | 0      |         0.4925 | True        |
| H1.2             | M1       | cpu_util_mean_transmit | treatment:payload | two-way ANOVA on sqrt(cpu_util_mean_transmit) |   1.1244 | 0.3501 | 0.3889 |         0.0476 | False       |
| H1.1             | M2       | cpu_time_compress_s    | treatment         | ART ANOVA                                     | 363.004  | 0      | 0      |         0.938  | True        |
| H1.2             | M2       | cpu_time_compress_s    | treatment:payload | ART ANOVA                                     |   1.9976 | 0.122  | 0.1743 |         0.0768 | False       |
| H1.1             | M2       | cpu_time_transmit_s    | treatment         | two-way ANOVA on log(cpu_time_transmit_s)     | 852.999  | 0      | 0      |         0.9743 | True        |
| H1.2             | M2       | cpu_time_transmit_s    | treatment:payload | two-way ANOVA on log(cpu_time_transmit_s)     |   0.3565 | 0.8389 | 0.8831 |         0.0156 | False       |
| H2.1             | M3       | wlan_tx_mb             | treatment         | ART ANOVA                                     | 276.293  | 0      | 0      |         0.9247 | True        |
| H2.2             | M3       | wlan_tx_mb             | treatment:payload | ART ANOVA                                     |   1.2058 | 0.3139 | 0.3693 |         0.0509 | False       |
| H2.1             | M5       | t_transmit_s           | treatment         | ART ANOVA                                     |  27.0422 | 0      | 0      |         0.5458 | True        |
| H2.2             | M5       | t_transmit_s           | treatment:payload | ART ANOVA                                     |   1.9077 | 0.116  | 0.1743 |         0.0782 | False       |
| H3.1             | M6       | energy_total_j         | treatment         | ART ANOVA                                     |  79.4647 | 0      | 0      |         0.7793 | True        |
| H3.2             | M6       | energy_total_j         | treatment:payload | ART ANOVA                                     |   1.4563 | 0.2222 | 0.2777 |         0.0608 | False       |
| (payload effect) | M6       | energy_total_j         | payload           | ART ANOVA                                     |   6.5802 | 0.012  | 0.0199 |         0.0681 | True        |
| H3.1             | M7       | energy_compress_j      | treatment         | ART ANOVA                                     | 185.69   | 0      | 0      |         0.8855 | True        |
| H3.2             | M7       | energy_compress_j      | treatment:payload | ART ANOVA                                     |   5.5057 | 0.0018 | 0.0037 |         0.1866 | True        |
| H3.1             | M7       | energy_transmit_j      | treatment         | ART ANOVA                                     |  28.539  | 0      | 0      |         0.5592 | True        |
| H3.2             | M7       | energy_transmit_j      | treatment:payload | ART ANOVA                                     |   1.4829 | 0.214  | 0.2777 |         0.0618 | False       |
| H3.3             | M8       | energy_per_mb_j        | payload           | ART ANOVA                                     |   6.5802 | 0.012  | 0.0199 |         0.0681 | True        |

## H3.4 net energy saving vs. baseline

| treatment   | payload   |   delta_j |   delta_pct |   ci95_low_j |   ci95_high_j | test              |   p_bh |   effect_size | energy_efficient   |
|:------------|:----------|----------:|------------:|-------------:|--------------:|:------------------|-------:|--------------:|:-------------------|
| zip         | S         |   -36.898 |     -14.678 |      -80.386 |         3.315 | Wilcoxon rank-sum |  0.521 |         -0.18 | False              |
| tar.gz      | S         |   -38.049 |     -15.136 |      -81.507 |         3.839 | Wilcoxon rank-sum |  0.521 |         -0.18 | False              |
| tar.zst     | S         |    94.068 |      37.42  |       49.439 |       136.238 | Wilcoxon rank-sum |  0.005 |          0.78 | True               |
| tar.br      | S         | -9738.6   |   -3873.96  |    -9943.71  |     -9579.74  | Wilcoxon rank-sum |  0.001 |         -1    | False              |
| zip         | L         |   -78.439 |     -37.399 |     -109.885 |       -44.048 | Wilcoxon rank-sum |  0.004 |         -0.82 | False              |
| tar.gz      | L         |   -82.162 |     -39.174 |     -115.129 |       -47.959 | Wilcoxon rank-sum |  0.004 |         -0.84 | False              |
| tar.zst     | L         |    63.01  |      30.043 |       30.341 |        98.95  | Wilcoxon rank-sum |  0.005 |          0.8  | True               |
| tar.br      | L         | -9738.87  |   -4643.44  |    -9929.87  |     -9621.65  | Wilcoxon rank-sum |  0.001 |         -1    | False              |

## H3.5 Spearman rho(M2, M6)

| hypothesis   | payload   |   n |   rho |   p |   p_bh |
|:-------------|:----------|----:|------:|----:|-------:|
| H3.5         | S         |  50 | 0.679 |   0 |      0 |
| H3.5         | L         |  50 | 0.819 |   0 |      0 |
