"""
ETL script to precompute and persist the TF-IDF vectorizer and matrix for street names.
"""

import pickle
from pathlib import Path

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer


def build_and_persist_tfidf():
    project_root = Path(__file__).resolve().parents[2]
    raw_data_path = project_root / "data" / "raw" / "nomenclator.csv"
    processed_data_dir = project_root / "data" / "processed"

    # Ensure processed directory exists
    processed_data_dir.mkdir(parents=True, exist_ok=True)

    print("Loading streets list...")
    streets_list = list(pd.read_csv(raw_data_path)["nom_oficial"])

    print("Fitting TF-IDF vectorizer...")
    tfidf_vectorizer = TfidfVectorizer(
        lowercase=True,
        strip_accents="unicode",
        ngram_range=(1, 4),
        token_pattern=r"(?u)\b\w+\b",
        use_idf=False,
    )

    tfidf_matrix = tfidf_vectorizer.fit_transform(streets_list)

    print("Persisting objects...")
    with open(processed_data_dir / "tfidf_vectorizer.pkl", "wb") as f:
        pickle.dump(tfidf_vectorizer, f)

    with open(processed_data_dir / "tfidf_matrix.pkl", "wb") as f:
        pickle.dump(tfidf_matrix, f)

    with open(processed_data_dir / "streets_list.pkl", "wb") as f:
        pickle.dump(streets_list, f)

    print(f"TF-IDF objects successfully persisted to {processed_data_dir}")


if __name__ == "__main__":
    build_and_persist_tfidf()
