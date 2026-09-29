{#-
    Percentile of each county-month value against that county's own EARLIER
    values only (DL-007, DL-022). Mid-rank for ties, so the result is in (0, 1).

    relation         a CTE with county_pcode, month and the value column
    value            name of the value column (NULLs are ignored on both sides)
    same_calendar_month
                     true: compare only with the same calendar month in earlier
                     years (seasonal series); false: compare with all earlier months
    min_history      fewer earlier values than this gives a NULL percentile

    Returns county_pcode, month, pct, n_history.
-#}
{% macro history_percentile(relation, value, same_calendar_month, min_history) %}
    select
        cur.county_pcode,
        cur.month,
        case when count(hist.{{ value }}) >= {{ min_history }} then
            (   count(*) filter (where hist.{{ value }} < cur.{{ value }})
              + 0.5 * count(*) filter (where hist.{{ value }} = cur.{{ value }})
            )::numeric / count(hist.{{ value }})
        end                              as pct,
        count(hist.{{ value }})          as n_history
    from {{ relation }} cur
    left join {{ relation }} hist
        on  hist.county_pcode = cur.county_pcode
        and hist.month < cur.month
        and hist.{{ value }} is not null
        {% if same_calendar_month %}
        and extract(month from hist.month) = extract(month from cur.month)
        {% endif %}
    where cur.{{ value }} is not null
    group by cur.county_pcode, cur.month
{% endmacro %}
