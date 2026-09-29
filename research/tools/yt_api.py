"""YouTube 내부 API(youtubei.googleapis.com)로 채널 영상 목록과 자막을 가져오는 도구."""
import json
import re
import sys
import urllib.request

BASE = "https://youtubei.googleapis.com/youtubei/v1/"
CONTEXT = {"client": {"clientName": "WEB", "clientVersion": "2.20250101.00.00", "hl": "ko", "gl": "KR"}}


def call(endpoint, body):
    body = {"context": CONTEXT, **body}
    req = urllib.request.Request(
        BASE + endpoint + "?prettyPrint=false",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def walk(obj, key):
    """중첩된 JSON에서 key를 가진 모든 값을 찾는다."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                yield v
            yield from walk(v, key)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v, key)


def text(node):
    if not node:
        return ""
    if "simpleText" in node:
        return node["simpleText"]
    if "runs" in node:
        return "".join(r.get("text", "") for r in node["runs"])
    if "content" in node:
        return node["content"]
    return ""


def channel_id(handle_url):
    r = call("navigation/resolve_url", {"url": handle_url})
    return next(walk(r, "browseId"))


def list_videos(cid, tab_params="EgZ2aWRlb3PyBgQKAjoA", limit=None):
    """채널의 영상 목록. tab_params 기본값은 '동영상' 탭."""
    videos, seen = [], set()
    r = call("browse", {"browseId": cid, "params": tab_params})
    while True:
        for v in walk(r, "videoRenderer"):
            vid = v.get("videoId")
            if vid and vid not in seen:
                seen.add(vid)
                videos.append({
                    "id": vid,
                    "title": text(v.get("title")),
                    "published": text(v.get("publishedTimeText")),
                    "views": text(v.get("viewCountText")),
                    "length": text(v.get("lengthText")),
                })
        for v in walk(r, "lockupViewModel"):
            vid = v.get("contentId")
            if vid and vid not in seen:
                seen.add(vid)
                title = next(walk(v, "title"), {})
                videos.append({"id": vid, "title": title.get("content", "") if isinstance(title, dict) else ""})
        if limit and len(videos) >= limit:
            return videos[:limit]
        # 정렬 칩 등의 토큰은 제외하고, 목록 끝의 '더 보기' 토큰만 사용
        tokens = [c for item in walk(r, "continuationItemRenderer") for c in walk(item, "continuationCommand")]
        if not tokens:
            return videos
        r = call("browse", {"continuation": tokens[0]["token"]})


def search_videos(query, limit=20):
    r = call("search", {"query": query})
    out = []
    for v in walk(r, "videoRenderer"):
        out.append({
            "id": v.get("videoId"),
            "title": text(v.get("title")),
            "channel": text(v.get("ownerText")),
            "published": text(v.get("publishedTimeText")),
            "views": text(v.get("viewCountText")),
        })
    return out[:limit]


def video_info(vid):
    r = call("next", {"videoId": vid})
    desc = next(walk(r, "attributedDescription"), None)
    return {"description": text(desc) if desc else ""}, r


def transcript(vid):
    """자막(대본). 없으면 None."""
    _, r = video_info(vid)
    params = [e["params"] for e in walk(r, "getTranscriptEndpoint")]
    if not params:
        return None
    t = call("get_transcript", {"params": params[0]})
    lines = []
    for seg in walk(t, "transcriptSegmentRenderer"):
        lines.append(text(seg.get("snippet")))
    return "\n".join(l for l in lines if l.strip()) or None


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "channel":
        print(channel_id(sys.argv[2]))
    elif cmd == "videos":
        lim = int(sys.argv[3]) if len(sys.argv) > 3 else None
        print(json.dumps(list_videos(sys.argv[2], limit=lim), ensure_ascii=False, indent=1))
    elif cmd == "search":
        print(json.dumps(search_videos(sys.argv[2]), ensure_ascii=False, indent=1))
    elif cmd == "desc":
        print(video_info(sys.argv[2])[0]["description"])
    elif cmd == "transcript":
        print(transcript(sys.argv[2]) or "(자막 없음)")


def comments(vid, limit=30):
    """영상 댓글(인기순 첫 페이지). 작성자 고정 댓글·질문답변에 요약이 있는 경우가 많다."""
    _, r = video_info(vid)
    toks = [c["token"] for item in walk(r, "continuationItemRenderer")
            for c in walk(item, "continuationCommand")]
    if not toks:
        return []
    c = call("next", {"continuation": toks[-1]})
    out = []
    for p in walk(c, "commentEntityPayload"):
        props = p.get("properties", {})
        author = p.get("author", {})
        out.append({
            "author": author.get("displayName", ""),
            "is_creator": author.get("isCreator", False),
            "text": props.get("content", {}).get("content", ""),
            "likes": p.get("toolbar", {}).get("likeCountNotliked", ""),
        })
    return out[:limit]


def details(vid):
    info, _ = video_info(vid)
    return {"id": vid, "description": info["description"], "comments": comments(vid)}


if __name__ == "__main__" and sys.argv[1] == "details":
    print(json.dumps(details(sys.argv[2]), ensure_ascii=False, indent=1))
