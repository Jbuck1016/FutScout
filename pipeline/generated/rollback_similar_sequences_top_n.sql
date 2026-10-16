CREATE OR REPLACE FUNCTION public.similar_sequences(p_seq text, p_n integer DEFAULT 10)
 RETURNS TABLE(rank integer, seq_uid text, team text, game_id text, n_pass integer, xt_sum numeric, ended_shot boolean, dist numeric)
 LANGUAGE sql
 STABLE
 SET search_path TO 'public', 'pg_temp'
 SET statement_timeout TO '8s'
AS $function$
  with q as (select * from public.seq_fz where seq_uid = p_seq)
  select row_number() over (order by d.dist)::int, d.seq_uid, d.team, d.game_id,
         d.n_pass, d.xt_sum, d.ended_shot, round(d.dist::numeric,3)
  from (
    select z.seq_uid, z.team, z.game_id, z.n_pass, z.xt_sum, z.ended_shot,
      sqrt(
        power(z.z_sx-q.z_sx,2)+power(z.z_sy-q.z_sy,2)+power(z.z_ex-q.z_ex,2)+power(z.z_ey-q.z_ey,2)
       +power(z.z_cx-q.z_cx,2)+power(z.z_cy-q.z_cy,2)+power(z.z_vs-q.z_vs,2)+power(z.z_ls-q.z_ls,2)
       +power(z.z_ndx-q.z_ndx,2)+power(z.z_ndy-q.z_ndy,2)+power(z.z_pl-q.z_pl,2)+power(z.z_np-q.z_np,2)
       +power(z.z_xt-q.z_xt,2)+power(z.z_as-q.z_as,2)
      ) as dist
    from public.seq_fz z, q
    where z.seq_uid <> q.seq_uid and z.game_id <> q.game_id
  ) d
  order by d.dist limit p_n;
$function$

