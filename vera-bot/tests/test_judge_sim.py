import sys
from pathlib import Path

# Add magicpin-ai-challenge to sys.path
CHALLENGE_DIR = Path("c:/VSCODE/PROJECTS/MagicPin/magicpin-ai-challenge")
sys.path.insert(0, str(CHALLENGE_DIR))

from judge_simulator import JudgeSimulator, LLMProvider, BotClient, LLMScorer

class MockLLM(LLMProvider):
    def complete(self, prompt: str, system: str = None) -> str:
        return '{"specificity": 9, "specificity_reason": "Specific clinical metrics and compliance deadline included", "category_fit": 9, "category_fit_reason": "Clinical peer-to-peer tone with Dr. salutation", "merchant_fit": 9, "merchant_fit_reason": "Personalized to Dr. Meera", "decision_quality": 9, "decision_quality_reason": "Relevant compliance trigger prioritized", "engagement_compulsion": 9, "engagement_reason": "Low friction binary CTA", "hint": "None"}'

    def name(self) -> str:
        return "MockLLM"

def run_tests():
    mock_llm = MockLLM()
    judge = JudgeSimulator(mock_llm)
    # Use 127.0.0.1 to avoid Windows localhost IPv6 resolution delay
    judge.client = BotClient("http://127.0.0.1:8080")
    
    print("\n--- Resetting Server State (Teardown) ---")
    judge.client._request("POST", "/v1/teardown", 5)

    print("\n--- Loading Dataset ---")
    loaded = judge.dataset.load()
    print("Dataset loaded:", loaded, f"({len(judge.dataset.categories)} categories, {len(judge.dataset.merchants)} merchants)")
    assert loaded is True, "Dataset load failed"

    judge.scorer = LLMScorer(judge.llm, judge.dataset)

    print("\n--- Running Warmup ---")
    assert judge._warmup() is True, "Warmup failed"

    print("\n--- Running Auto-reply ---")
    assert judge._auto_reply() is True, "Auto-reply failed"

    print("\n--- Running Intent Transition ---")
    assert judge._intent() is True, "Intent transition failed"

    print("\n--- Running Phase 2 Short ---")
    judge.client._request("POST", "/v1/teardown", 5)
    assert judge._phase2_short() is True, "Phase 2 short failed"

    print("\n--- Running Hostile ---")
    assert judge._hostile() is True, "Hostile handling failed"

    print("\n--- Running Full Evaluation ---")
    judge.client._request("POST", "/v1/teardown", 5)
    assert judge._full() is True, "Full evaluation failed"

    print("\n--- Final Summary ---")
    judge._final_summary()

    print("\n>>> ALL JUDGE SIMULATOR SCENARIOS PASSED WITH FLYING COLORS! <<<")

if __name__ == "__main__":
    run_tests()
