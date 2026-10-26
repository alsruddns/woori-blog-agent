export type Language = { code: string; display_name: string; active: boolean };
export type Blog = {
  id: string;
  language_code: string;
  display_name: string;
  url: string;
  active: boolean;
  blog_id: string | null;
};
export type Profile = {
  id: string;
  language_code: string;
  target_country: string;
  search_intent: string;
  generation_policy: string;
  localization_policy: string;
  seo_policy: string;
};
export type Policy = {
  id: string;
  blog_id: string;
  profile_id: string;
  timezone: string;
  schedule_cron: string;
  active: boolean;
  auto_publish_allowed: boolean;
};
export type Config = {
  languages: Language[];
  blogs: Blog[];
  profiles: Profile[];
  policies: Policy[];
  readiness: {
    profile_id: string;
    connection_id: string | null;
    language_code: string;
    target_country: string;
    generation_possible: boolean;
    translation_possible: boolean;
    quality_possible: boolean;
    blogger_connected: boolean;
    test_publish_verified: boolean;
    automatic_publishing_allowed: boolean;
    blocked_reason: string;
  }[];
  glossary: {
    id: string;
    profile_id: string;
    source_term: string;
    localized_term: string;
    notes: string;
    source_language: string;
    target_language: string;
    official_translation: boolean;
    translation_source: string | null;
    approved: boolean;
  }[];
  categories: { id: string; slug: string }[];
  category_localizations: {
    category_id: string;
    profile_id: string;
    display_name: string;
  }[];
  performance: {
    language_code: string;
    country: string;
    clicks: number;
    impressions: number;
  }[];
};
