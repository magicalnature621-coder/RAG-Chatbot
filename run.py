import os
import sys
import uvicorn

# Add current folder to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backend.database import init_db
from backend.rag.pipeline import get_rag_pipeline
from backend.crawler.crawler import CollegeCrawler

def main():
    print("=" * 65)
    print("  IIIT Kottayam CampusBot - RAG Conversational AI Web App")
    print("=" * 65)
    
    # 1. Initialize Database
    print("[1/3] Initializing SQLite database...")
    init_db()

    # 2. Check Vector Index
    print("[2/3] Checking vector knowledge base...")
    pipeline = get_rag_pipeline()
    stats = pipeline.vector_store.get_stats()
    
    if stats["total_chunks"] == 0:
        print("      No index found. Crawling initial IIIT Kottayam pages (Admissions, Placements, B.Tech, Faculty)...")
        crawler = CollegeCrawler(vector_store=pipeline.vector_store)
        res = crawler.run_sync(target_url="https://iiitkottayam.ac.in/#!/home")
        print(f"      Initial crawl completed: {res['crawled']} pages crawled, {res['chunks_indexed']} vector chunks created.")
    else:
        print(f"      Knowledge base active: {stats['total_documents']} documents, {stats['total_chunks']} vector chunks.")

    # 3. Launch Server
    print("[3/3] Starting web server on http://127.0.0.1:8000 ...")
    print("      Open your browser and navigate to: http://127.0.0.1:8000")
    print("=" * 65)

    uvicorn.run(
        "backend.main:app",
        host="127.0.0.1",
        port=8000,
        reload=False
    )

if __name__ == "__main__":
    main()
