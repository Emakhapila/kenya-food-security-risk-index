{#- The forecast script (modelling/forecast_maize.py) appends one batch of rows per
    run; nothing is updated or deleted (DL-025). Created here, before every dbt
    run, so marts.fct_price_forecast can always be built, even before the first
    forecast exists. -#}
{% macro create_forecast_table() %}
    create schema if not exists forecasts;
    create table if not exists forecasts.maize_price_forecast_runs (
        run_at                  timestamptz not null,
        origin_month            date        not null,
        target_month            date        not null,
        horizon                 integer     not null check (horizon between 1 and 3),
        county_pcode            text        not null,
        model                   text        not null,
        last_price_kes_per_kg   numeric     not null,
        forecast_kes_per_kg     numeric     not null,
        lower_80_kes_per_kg     numeric     not null,
        upper_80_kes_per_kg     numeric     not null,
        interval_errors_n       integer     not null,
        is_low_resolution       boolean     not null,
        primary key (run_at, county_pcode, horizon)
    );
{% endmacro %}
