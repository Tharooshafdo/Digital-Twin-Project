from tl_twin.contracts import load_configs
from tl_twin.physics import solve_line, solve_abcd

cfg = load_configs("config/lines.json")[0]
print(solve_line(cfg, 132.1, 66.8, 13.5))
print(solve_abcd(cfg, 132.1, 66.8, 13.5))
