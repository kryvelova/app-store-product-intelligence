# App Store Product Intelligence

## Goal

Build a real-world analytics engineering project using public Apple
App Store data.

Initial focus:
- macOS applications

The architecture must be extensible to other companies, countries,
categories, and eventually other Apple platforms.

## Stack

- Python
- Apple iTunes Search API
- BigQuery
- dbt
- SQL
- GitHub Actions

## Architecture

Apple API
    ↓
Python ingestion
    ↓
BigQuery raw layer
    ↓
dbt transformations
    ↓
Analytics marts
    ↓
Product / market intelligence

## Important principles

- Use real data only.
- Do not invent business data.
- Preserve raw API responses where practical.
- Every collected record must have a snapshot_date.
- Keep ingestion separate from dbt transformations.
- Do not hard-code company name into the data models.
- Make the pipeline configurable for other companies.
- Prefer simple, maintainable solutions.
- Add tests for important transformations.
- Do not introduce unnecessary infrastructure.

## Development rules

Before implementing a significant change:
1. Explain the proposed approach.
2. Keep changes focused.
3. Add tests where appropriate.
4. Run relevant tests/linting.
5. Do not modify unrelated files.

