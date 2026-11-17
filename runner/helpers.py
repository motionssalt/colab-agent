"""Terminal-visible search and fetch. Failures are explicit, bounded, non-secret."""
import argparse,sys

def search_main():
    p=argparse.ArgumentParser();p.add_argument('query');p.add_argument('-n',type=int,default=8);a=p.parse_args()
    try:
        from ddgs import DDGS
        rows=list(DDGS(timeout=20).text(a.query,max_results=max(1,min(a.n,20))))
        if not rows:raise RuntimeError('No search results returned; try a different query')
        for i,r in enumerate(rows,1):print(f"{i}. {r.get('title','')}\n{r.get('href','')}\n{r.get('body','')}\n")
    except Exception as e:print('Search unavailable: '+type(e).__name__+'. Retry later or use fetch with a known URL.',file=sys.stderr);return 1
    return 0

def fetch_main():
    p=argparse.ArgumentParser();p.add_argument('url');p.add_argument('--max-chars',type=int,default=16000);a=p.parse_args()
    try:
        import httpx,trafilatura
        if not a.url.startswith(('http://','https://')):raise ValueError('HTTP(S) URL required')
        with httpx.Client(follow_redirects=True,timeout=25) as c:
            with c.stream('GET',a.url) as response:
                response.raise_for_status();data=bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data)>5000000:raise ValueError('Page exceeds 5 MB')
        text=trafilatura.extract(data.decode('utf8','replace'))
        if not text:raise ValueError('No readable text extracted')
        print(text[:max(100,min(100000,a.max_chars))])
    except Exception as e:print('Fetch unavailable: '+type(e).__name__+'. Check URL or try another source.',file=sys.stderr);return 1
    return 0
if __name__=='__main__':sys.exit(search_main() if sys.argv.pop(1)=='search' else fetch_main())
