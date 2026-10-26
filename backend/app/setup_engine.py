import json
from pathlib import Path
from .conditions import CONDITION_REGISTRY

SETUPS_DIR = Path(__file__).parent / "setups"


def load_setup(setup_id: str) -> dict:
    if setup_id not in {f.stem for f in SETUPS_DIR.glob("*.json")}:
        raise ValueError(f"Unknown setup: {setup_id}")
    path = SETUPS_DIR / f"{setup_id}.json"
    if not path.exists():
        raise ValueError(f"Unknown setup: {setup_id}")
    return json.loads(path.read_text())


def list_setups() -> list[dict]:
    out = []
    for f in sorted(SETUPS_DIR.glob("*.json")):
        cfg = json.loads(f.read_text())
        out.append({"id": cfg["id"], "name": cfg["name"], "description": cfg.get("description", ""),
                     "direction": cfg.get("direction", "bullish")})
    return out


def evaluate_setup(symbol: str, setup_config: dict, timeframe_data: dict) -> dict:
    result = {"symbol": symbol, "setup": setup_config["id"], "timeframes": {}}
    total_conditions = 0
    total_passed = 0

    for timeframe, conditions in setup_config["timeframes"].items():
        df = timeframe_data.get(timeframe)
        tf_result = {"passed": True, "conditions": {}}

        if df is None or len(df) < 30:
            tf_result["passed"] = False
            tf_result["error"] = "insufficient data"
            result["timeframes"][timeframe] = tf_result
            continue

        for cond_spec in conditions:
            cond_name = cond_spec["condition"]
            cond_id = cond_spec["id"]
            fn = CONDITION_REGISTRY.get(cond_name)
            if fn is None:
                raise ValueError(f"Unregistered condition: {cond_name}")

            try:
                cond_result = fn(df)
            except Exception as e:
                cond_result = {"passed": False, "detail": f"error: {e}"}

            tf_result["conditions"][cond_id] = cond_result
            total_conditions += 1
            if cond_result["passed"]:
                total_passed += 1
            else:
                tf_result["passed"] = False

        result["timeframes"][timeframe] = tf_result

    result["qualified"] = all(tf["passed"] for tf in result["timeframes"].values())
    result["score"] = round(100 * total_passed / total_conditions, 1) if total_conditions else 0.0
    result["conditions_passed"] = total_passed
    result["conditions_total"] = total_conditions
    return result
