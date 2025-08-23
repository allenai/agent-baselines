import json
from pathlib import Path

from datasets import Dataset

DATA_DIR = Path(__file__).parent / "responses"
HF_USERNAME = "allenai"
DS_NAME = "scispace_sqa_responses"


def load_samples(data_dir):
    samples = []
    for k, v in json.load(open("case_id_to_answer_text_format.json")).items():
        samples.append({"id": k, "report": v})
    return samples


def main():
    samples = load_samples(DATA_DIR)
    ds = Dataset.from_list(samples)
    hf_path = f"{HF_USERNAME}/{DS_NAME}"
    ds.push_to_hub(hf_path, private=True)


if __name__ == "__main__":
    main()
