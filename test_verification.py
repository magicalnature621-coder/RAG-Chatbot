import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.database import init_db, get_user_by_username, get_crawled_page
from backend.auth import register_user, authenticate_user
from backend.rag.pipeline import get_rag_pipeline
from backend.crawler.crawler import CollegeCrawler

def test_system():
    print("--- [1] Testing Database Initialization ---")
    init_db()
    print("Database tables initialized successfully.")

    print("\n--- [2] Testing User Auth & Session Tokens ---")
    username = "test_student"
    password = "secretpassword123"
    
    # Try register
    try:
        reg_res = register_user(username, password, "test@iiitkottayam.ac.in")
        print(f"User registered: {reg_res['user']['username']}, Token generated.")
    except Exception as e:
        print(f"User might already exist: {e}")

    # Login
    auth_res = authenticate_user(username, password)
    assert auth_res["token"], "Token missing!"
    print(f"Login successful for user id {auth_res['user']['id']}.")

    print("\n--- [3] Testing IIIT Kottayam Crawler & Document Loader ---")
    pipeline = get_rag_pipeline()
    crawler = CollegeCrawler(vector_store=pipeline.vector_store)
    
    # Crawl top 5 priority views for rapid test verification
    stats = crawler.crawl_iiit_kottayam(base_url="https://iiitkottayam.ac.in", max_views=8)
    print(f"Crawl finished: {stats['crawled']} views processed, {stats['chunks_indexed']} vector chunks created.")
    assert stats["crawled"] > 0, "No pages were crawled!"

    # Verify SHA-256 hash in DB
    placement_page = get_crawled_page("https://iiitkottayam.ac.in/#!/placement")
    assert placement_page is not None, "Placement page not in database!"
    print(f"Verified placement page in DB: title='{placement_page['title']}', hash={placement_page['content_hash'][:16]}..., chunks={placement_page['chunk_count']}")

    print("\n--- [4] Testing RAG Retrieval & Question Answering ---")
    test_query = "What is the highest placement CTC package at IIIT Kottayam?"
    result = pipeline.query(test_query)
    
    print(f"Query: {test_query}")
    print(f"Answer snippet: {result['answer'][:250]}...")
    print(f"Provider: {result['provider']}")
    print(f"Sources retrieved: {len(result['sources'])}")
    for s in result["sources"]:
        print(f"  - [{s['title']}] ({s['url']}) Score: {s['score']}")

    assert len(result["sources"]) > 0, "No sources retrieved!"
    print("\n>>> ALL TESTS PASSED SUCCESSFULLY! <<<")

if __name__ == "__main__":
    test_system()
