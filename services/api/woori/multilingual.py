"""Database-driven configuration. No external service clients are used here."""

from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import langcodes
import psycopg
from fastapi import APIRouter, HTTPException
from psycopg import sql
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .db import connection

router = APIRouter(prefix="/admin/config")
# Only verified adapters may enter these registries in a later approved implementation.
GENERATION_ADAPTERS: dict[str, set[str]] = {}
TRANSLATION_ADAPTERS: dict[str, set[str]] = {}
QUALITY_ADAPTERS: dict[str, set[str]] = {}


def language_tag(value: str) -> str:
    if "_" in value or not langcodes.tag_is_valid(value):
        raise ValueError("Use a valid BCP 47 language tag")
    return str(langcodes.standardize_tag(value))


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LanguageInput(Input):
    code: str = Field(min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=100)
    active: bool = True
    _tag = field_validator("code")(language_tag)


class LanguageUpdate(Input):
    display_name: str = Field(min_length=1, max_length=100)
    active: bool


class BlogInput(Input):
    language_code: str = Field(max_length=100)
    url: str = Field(pattern=r"^https://[a-z0-9][a-z0-9-]*\.blogspot\.com/?$")
    display_name: str = Field(min_length=1, max_length=100)
    active: bool = True
    _tag = field_validator("language_code")(language_tag)

    @field_validator("url")
    @classmethod
    def normalize_url(cls, value: str) -> str:
        return value.rstrip("/")


class ProfileInput(Input):
    language_code: str = Field(max_length=100)
    target_country: str = Field(default="", pattern=r"^([A-Z]{2}|[0-9]{3})?$")
    search_intent: str = Field(default="", max_length=2000)
    generation_policy: str = Field(default="", max_length=2000)
    localization_policy: str = Field(default="", max_length=2000)
    seo_policy: str = Field(default="", max_length=2000)
    _tag = field_validator("language_code")(language_tag)


class PolicyInput(Input):
    blog_id: UUID
    profile_id: UUID
    active: bool = False
    timezone: str = Field(default="UTC", max_length=100)
    schedule_cron: str = Field(default="0 9 * * *", max_length=100)

    @field_validator("timezone")
    @classmethod
    def valid_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Unknown IANA timezone") from None
        return value

    @field_validator("schedule_cron")
    @classmethod
    def valid_cron(cls, value: str) -> str:
        from croniter import croniter

        if len(value.split()) != 5 or not croniter.is_valid(value):
            raise ValueError("Use a valid five-field cron schedule")
        return value


class GlossaryInput(Input):
    profile_id: UUID
    source_term: str = Field(min_length=1, max_length=200)
    localized_term: str = Field(min_length=1, max_length=200)
    notes: str = Field(default="", max_length=1000)


class CommonCategoryInput(Input):
    slug: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")


class CategoryInput(Input):
    category_id: UUID
    profile_id: UUID
    display_name: str = Field(min_length=1, max_length=100)


def save(
    table: str, values: dict[str, Any], conflict: list[str], *, update: bool = True
) -> dict[str, Any]:
    # All identifiers originate in typed server code; never accept table/column names from HTTP.
    columns = list(values)
    statement = sql.SQL("INSERT INTO {} ({}) VALUES ({}) ON CONFLICT ({}) ").format(
        sql.Identifier(table),
        sql.SQL(",").join(map(sql.Identifier, columns)),
        sql.SQL(",").join(sql.Placeholder() for _ in columns),
        sql.SQL(",").join(map(sql.Identifier, conflict)),
    )
    if update:
        statement += sql.SQL("DO UPDATE SET ") + sql.SQL(",").join(
            sql.SQL("{}=EXCLUDED.{}").format(sql.Identifier(k), sql.Identifier(k))
            for k in columns
            if k not in conflict
        )
    else:
        statement += sql.SQL("DO NOTHING")
    statement += sql.SQL(" RETURNING *")
    try:
        with connection() as conn:
            conn.execute("SELECT set_config('woori.actor','local_admin',true)")
            row = conn.execute(statement, tuple(values.values())).fetchone()
            if row is None:
                raise HTTPException(409, "Already registered")
            if table == "languages":
                profile = conn.execute(
                    "INSERT INTO language_profiles(language_code) VALUES (%s) RETURNING id",
                    (row["code"],),
                ).fetchone()
                assert profile is not None
                conn.execute(
                    "INSERT INTO language_capabilities(profile_id) VALUES (%s)", (profile["id"],)
                )
            if table == "language_profiles":
                conn.execute(
                    "INSERT INTO language_capabilities(profile_id) VALUES (%s) ON CONFLICT DO NOTHING",
                    (row["id"],),
                )
            return row
    except psycopg.IntegrityError:
        raise HTTPException(409, "Configuration conflicts with existing references") from None
    except psycopg.Error:
        raise HTTPException(503, "Database unavailable") from None


@router.post("/languages", status_code=201)
def add_language(request: LanguageInput) -> dict[str, Any]:
    return save("languages", request.model_dump(), ["code"], update=False)


@router.patch("/languages/{code}")
def update_language(code: str, request: LanguageUpdate) -> dict[str, Any]:
    try:
        code = language_tag(code)
    except ValueError:
        raise HTTPException(422, "Invalid language tag") from None
    try:
        with connection() as conn:
            conn.execute("SELECT set_config('woori.actor','local_admin',true)")
            row = conn.execute(
                "UPDATE languages SET display_name=%s,active=%s WHERE code=%s RETURNING *",
                (request.display_name, request.active, code),
            ).fetchone()
            if row is None:
                raise HTTPException(404, "Language not found")
            return row
    except psycopg.Error:
        raise HTTPException(503, "Database unavailable") from None


@router.post("/blogs", status_code=201)
def add_blog(request: BlogInput) -> dict[str, Any]:
    return save("blogger_blogs", request.model_dump(), ["url"], update=False)


@router.patch("/blogs/{blog_id}")
def update_blog(blog_id: UUID, request: LanguageUpdate) -> dict[str, Any]:
    try:
        with connection() as conn:
            conn.execute("SELECT set_config('woori.actor','local_admin',true)")
            row = conn.execute(
                "UPDATE blogger_blogs SET display_name=%s,active=%s WHERE id=%s RETURNING *",
                (request.display_name, request.active, blog_id),
            ).fetchone()
            if row is None:
                raise HTTPException(404, "Blog not found")
            return row
    except psycopg.Error:
        raise HTTPException(503, "Database unavailable") from None


@router.post("/profiles")
def save_profile(request: ProfileInput) -> dict[str, Any]:
    return save("language_profiles", request.model_dump(), ["language_code", "target_country"])


@router.post("/policies")
def save_policy(request: PolicyInput) -> dict[str, Any]:
    try:
        with connection() as conn:
            blog = conn.execute(
                "SELECT language_code FROM blogger_blogs WHERE id=%s", (request.blog_id,)
            ).fetchone()
        if blog is None:
            raise HTTPException(404, "Blog not found")
        return save(
            "publishing_policies",
            {"language_code": blog["language_code"], **request.model_dump()},
            ["blog_id", "profile_id"],
        )
    except psycopg.Error:
        raise HTTPException(503, "Database unavailable") from None


@router.post("/glossary")
def save_glossary(request: GlossaryInput) -> dict[str, Any]:
    return save("glossary_entries", request.model_dump(), ["profile_id", "source_term"])


@router.post("/categories", status_code=201)
def add_category(request: CommonCategoryInput) -> dict[str, Any]:
    return save("categories", request.model_dump(), ["slug"], update=False)


@router.post("/category-localizations")
def save_category(request: CategoryInput) -> dict[str, Any]:
    return save("category_localizations", request.model_dump(), ["category_id", "profile_id"])


def readiness(row: dict[str, Any]) -> dict[str, Any]:
    code = row["language_code"]
    result = {
        **row,
        "generation_possible": bool(
            row["generation_supported"]
            and code in GENERATION_ADAPTERS.get(row["model_adapter"], set())
        ),
        "translation_possible": bool(
            row["translation_supported"]
            and code in TRANSLATION_ADAPTERS.get(row["model_adapter"], set())
        ),
        "quality_possible": bool(
            row["quality_supported"]
            and code in QUALITY_ADAPTERS.get(row["validator_adapter"], set())
        ),
        "blogger_connected": row["blog_id"] is not None
        and row["connection_verified_at"] is not None,
        "test_publish_verified": row["test_publish_verified_at"] is not None,
        "automatic_publishing_allowed": False,
        "blocked_reason": "Phase 1: external publishing and AI adapters are disabled",
    }
    return result


@router.get("")
def configuration() -> dict[str, Any]:
    try:
        with connection() as conn:
            result: dict[str, Any] = {}
            for key, table in [
                ("languages", "languages"),
                ("blogs", "blogger_blogs"),
                ("profiles", "language_profiles"),
                ("policies", "publishing_policies"),
                ("categories", "categories"),
                ("category_localizations", "category_localizations"),
                ("glossary", "glossary_entries"),
            ]:
                result[key] = conn.execute(
                    sql.SQL("SELECT * FROM {} ORDER BY 1").format(sql.Identifier(table))
                ).fetchall()
            rows = conn.execute("""SELECT p.id AS profile_id,p.language_code,p.target_country,
                l.active AS language_active,c.*,b.id AS connection_id,b.active AS blog_active,
                b.blog_id,b.connection_verified_at,b.test_publish_verified_at
                FROM language_profiles p JOIN languages l ON l.code=p.language_code
                JOIN language_capabilities c ON c.profile_id=p.id
                LEFT JOIN blogger_blogs b ON b.language_code=p.language_code ORDER BY p.language_code""").fetchall()
            result["readiness"] = [readiness(row) for row in rows]
            result["performance"] = conn.execute("""SELECT b.language_code,s.country,
                sum(s.clicks) AS clicks,sum(s.impressions) AS impressions
                FROM search_performance s JOIN blogger_blogs b ON b.id=s.blog_id
                GROUP BY b.language_code,s.country ORDER BY b.language_code,s.country""").fetchall()
            return result
    except psycopg.Error:
        raise HTTPException(503, "Database unavailable") from None
