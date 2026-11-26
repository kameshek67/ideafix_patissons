from typing import Any

from .client import Json

Object = dict[str, Any]


def objects(value: Any) -> list[Object]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def obj(value: Any) -> Object:
    return value if isinstance(value, dict) else {}


def text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def name(row: Object) -> str:
    return (
        text(row.get("short_name"))
        or text(row.get("canonical_name"))
        or text(row.get("name"))
        or text(row.get("faculty_or_direction"))
    )


def sources(data: Any) -> list[Object]:
    found: dict[str, Object] = {}

    def add(url: Any, title: Any, university: str) -> None:
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            return
        source: Object = {"url": url}
        label = text(title)
        if label:
            source["title"] = label
        if university:
            source["university"] = university
        existing = found.get(url)
        if existing is None:
            found[url] = source
            return
        for key in ("title", "university"):
            if not existing.get(key) and source.get(key):
                existing[key] = source[key]

    def walk(node: Any, university: str = "", in_sources: bool = False) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item, university, in_sources)
        elif isinstance(node, dict):
            owner = (
                text(node.get("university"))
                or text(node.get("university_short"))
                or name(obj(node.get("university")))
                or text(node.get("short_name"))
                or university
            )
            if node.get("docs_url"):
                add(node["docs_url"], node.get("docs_title"), owner)
            if node.get("source_url"):
                add(node["source_url"], node.get("source_title"), owner)
            if in_sources and node.get("url"):
                add(node["url"], node.get("title"), owner)
            for key, value in node.items():
                if key != "card":
                    walk(value, owner or text(node.get("name")), in_sources or key == "sources")

    walk(data)
    return list(found.values())


def olympiads(data: Json) -> Json:
    return {
        "items": [
            {
                "id": item.get("id"),
                "name": name(item),
                "kind": text(item.get("kind")),
                "bvi": item.get("bvi_count", 0),
                "sto": item.get("sto_count", 0),
                "universities": item.get("uni_count", 0),
            }
            for item in objects(data.get("items"))
        ],
        "sources": sources(data),
    }


def benefits_by_olympiad(data: Json) -> Json:
    return {
        "olympiads": [
            {"id": item.get("id"), "name": name(item)}
            for item in objects(data.get("matched_olympiads"))
        ],
        "universities": [
            {
                "id": obj(item.get("university")).get("id"),
                "name": name(obj(item.get("university"))),
                "programs": item.get("programs_total", 0),
                "bvi": item.get("bvi", 0),
                "sto": item.get("sto", 0),
                "other": item.get("other", 0),
            }
            for item in objects(data.get("results"))
        ],
        "sources": sources(data),
    }


def university_programs(universities: Json, programs: Json) -> Json:
    return {
        "universities": [
            {
                "id": item.get("id"),
                "name": name(item),
                "programs": item.get("programs", 0),
                "bvi": item.get("bvi", 0),
                "sto": item.get("sto", 0),
            }
            for item in objects(universities.get("items"))
        ],
        "programs": [
            {
                "id": item.get("id"),
                "university": text(item.get("university")),
                "name": name(item),
                "code": text(item.get("code")),
                "profile": text(item.get("profile_name")),
            }
            for item in objects(programs.get("items"))
        ],
        "sources": sources([universities, programs]),
    }


def olympiads_for_program(data: Json) -> Json:
    program = obj(data.get("program"))
    return {
        "program": {
            "id": program.get("id"),
            "name": name(program),
            "code": text(program.get("code")),
            "university": name(obj(data.get("university"))),
        },
        "olympiads": [
            {
                "id": item.get("id"),
                "name": name(item),
                "types": [text(t) for t in item.get("types", []) if isinstance(t, str)],
                "count": item.get("count", 0),
            }
            for item in objects(data.get("olympiads"))
        ],
        "sources": sources(data),
    }


def match_diplomas(data: Json) -> Json:
    return {
        "diplomas": [
            {
                "spec": text(item.get("spec")),
                "found": bool(item.get("found")),
                "olympiad": name(obj(item.get("olympiad"))),
                "profile": name(obj(item.get("profile"))),
                "role": text(item.get("role")),
                "year": item.get("year"),
            }
            for item in objects(data.get("diplomas"))
        ],
        "universities": [
            {
                "id": obj(item.get("university")).get("id"),
                "name": name(obj(item.get("university"))),
                "bvi": item.get("bvi", 0),
                "sto": item.get("sto", 0),
                "other": item.get("other", 0),
            }
            for item in objects(data.get("results"))
        ],
        "totals": obj(data.get("totals")),
        "sources": sources(data),
    }
