-- Counter-attacking sequences do not imply a passive press. PPDA's direction is
-- inverse: lower values indicate more active pressing. Patch the deployed
-- generator in place to preserve all other post-deployment function changes.
do $migration$
declare
  v_def text;
  v_old text := $old$They do it with only %s%% of the ball and a passive press (PPDA %s), which is the shape of a side that invites pressure and punishes the turnover.$old$;
  v_new text := $new$They average %s%% possession and PPDA %s (lower PPDA means more aggressive pressing). Those measures alone do not establish whether they invite pressure.$new$;
begin
  select pg_get_functiondef('public.build_insights_extra()'::regprocedure) into v_def;
  if v_def is null or (length(v_def) - length(replace(v_def, v_old, ''))) <> length(v_old) then
    raise exception 'Counter-attack generator changed: expected exactly one known phrase';
  end if;
  execute replace(v_def, v_old, v_new);
end
$migration$;

-- Correct published rows without running a full analytics rebuild.
update public.insights
set detail = split_part(detail, 'They do it with only ', 1) ||
  format('They average %s%% possession and PPDA %s (lower PPDA means more aggressive pressing). Those measures alone do not establish whether they invite pressure.',
    metrics->>'possession_pct', metrics->>'ppda')
where detector = 'counter_attack'
  and detail like '%a passive press%'
  and metrics ? 'possession_pct'
  and metrics ? 'ppda';
