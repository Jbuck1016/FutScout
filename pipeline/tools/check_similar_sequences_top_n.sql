begin read only; set local statement_timeout='8s'; with test_fz as (select v.seq_uid, v.game_id, 'test'::text team, 3::integer n_pass, 0::numeric xt_sum, false ended_shot, v.x::numeric z_sx, 0::numeric z_sy,0::numeric z_ex,0::numeric z_ey,0::numeric z_cx,0::numeric z_cy,0::numeric z_vs,0::numeric z_ls,0::numeric z_ndx,0::numeric z_ndy,0::numeric z_pl,0::numeric z_np,0::numeric z_xt,0::numeric z_as from (values ('q','g0',0),('same','g0',0.1),('c','g3',1),('b','g2',1),('a','g1',1),('z-near','g4',1.0001),('a-far','g5',1.0002)) v(seq_uid,game_id,x)),  ties(rank,seq_uid,team,game_id,n_pass,xt_sum,ended_shot,dist) as (with q as (select * from test_fz where seq_uid = 'q')
  select row_number() over (order by d.dist, d.seq_uid)::int, d.seq_uid, d.team, d.game_id,
         d.n_pass, d.xt_sum, d.ended_shot, round(d.dist::numeric,3)
  from (
    select z.seq_uid, z.team, z.game_id, z.n_pass, z.xt_sum, z.ended_shot,
      sqrt(
        power(z.z_sx-q.z_sx,2)+power(z.z_sy-q.z_sy,2)+power(z.z_ex-q.z_ex,2)+power(z.z_ey-q.z_ey,2)
       +power(z.z_cx-q.z_cx,2)+power(z.z_cy-q.z_cy,2)+power(z.z_vs-q.z_vs,2)+power(z.z_ls-q.z_ls,2)
       +power(z.z_ndx-q.z_ndx,2)+power(z.z_ndy-q.z_ndy,2)+power(z.z_pl-q.z_pl,2)+power(z.z_np-q.z_np,2)
       +power(z.z_xt-q.z_xt,2)+power(z.z_as-q.z_as,2)
      ) as dist
    from test_fz z, q
    where z.seq_uid <> q.seq_uid and z.game_id <> q.game_id
    order by dist, z.seq_uid limit 2
  ) d
  order by d.dist, d.seq_uid), allrows(rank,seq_uid,team,game_id,n_pass,xt_sum,ended_shot,dist) as (with q as (select * from test_fz where seq_uid = 'q')
  select row_number() over (order by d.dist, d.seq_uid)::int, d.seq_uid, d.team, d.game_id,
         d.n_pass, d.xt_sum, d.ended_shot, round(d.dist::numeric,3)
  from (
    select z.seq_uid, z.team, z.game_id, z.n_pass, z.xt_sum, z.ended_shot,
      sqrt(
        power(z.z_sx-q.z_sx,2)+power(z.z_sy-q.z_sy,2)+power(z.z_ex-q.z_ex,2)+power(z.z_ey-q.z_ey,2)
       +power(z.z_cx-q.z_cx,2)+power(z.z_cy-q.z_cy,2)+power(z.z_vs-q.z_vs,2)+power(z.z_ls-q.z_ls,2)
       +power(z.z_ndx-q.z_ndx,2)+power(z.z_ndy-q.z_ndy,2)+power(z.z_pl-q.z_pl,2)+power(z.z_np-q.z_np,2)
       +power(z.z_xt-q.z_xt,2)+power(z.z_as-q.z_as,2)
      ) as dist
    from test_fz z, q
    where z.seq_uid <> q.seq_uid and z.game_id <> q.game_id
    order by dist, z.seq_uid limit NULL
  ) d
  order by d.dist, d.seq_uid), zero(rank,seq_uid,team,game_id,n_pass,xt_sum,ended_shot,dist) as (with q as (select * from test_fz where seq_uid = 'q')
  select row_number() over (order by d.dist, d.seq_uid)::int, d.seq_uid, d.team, d.game_id,
         d.n_pass, d.xt_sum, d.ended_shot, round(d.dist::numeric,3)
  from (
    select z.seq_uid, z.team, z.game_id, z.n_pass, z.xt_sum, z.ended_shot,
      sqrt(
        power(z.z_sx-q.z_sx,2)+power(z.z_sy-q.z_sy,2)+power(z.z_ex-q.z_ex,2)+power(z.z_ey-q.z_ey,2)
       +power(z.z_cx-q.z_cx,2)+power(z.z_cy-q.z_cy,2)+power(z.z_vs-q.z_vs,2)+power(z.z_ls-q.z_ls,2)
       +power(z.z_ndx-q.z_ndx,2)+power(z.z_ndy-q.z_ndy,2)+power(z.z_pl-q.z_pl,2)+power(z.z_np-q.z_np,2)
       +power(z.z_xt-q.z_xt,2)+power(z.z_as-q.z_as,2)
      ) as dist
    from test_fz z, q
    where z.seq_uid <> q.seq_uid and z.game_id <> q.game_id
    order by dist, z.seq_uid limit 0
  ) d
  order by d.dist, d.seq_uid), missing(rank,seq_uid,team,game_id,n_pass,xt_sum,ended_shot,dist) as (with q as (select * from test_fz where seq_uid = 'missing')
  select row_number() over (order by d.dist, d.seq_uid)::int, d.seq_uid, d.team, d.game_id,
         d.n_pass, d.xt_sum, d.ended_shot, round(d.dist::numeric,3)
  from (
    select z.seq_uid, z.team, z.game_id, z.n_pass, z.xt_sum, z.ended_shot,
      sqrt(
        power(z.z_sx-q.z_sx,2)+power(z.z_sy-q.z_sy,2)+power(z.z_ex-q.z_ex,2)+power(z.z_ey-q.z_ey,2)
       +power(z.z_cx-q.z_cx,2)+power(z.z_cy-q.z_cy,2)+power(z.z_vs-q.z_vs,2)+power(z.z_ls-q.z_ls,2)
       +power(z.z_ndx-q.z_ndx,2)+power(z.z_ndy-q.z_ndy,2)+power(z.z_pl-q.z_pl,2)+power(z.z_np-q.z_np,2)
       +power(z.z_xt-q.z_xt,2)+power(z.z_as-q.z_as,2)
      ) as dist
    from test_fz z, q
    where z.seq_uid <> q.seq_uid and z.game_id <> q.game_id
    order by dist, z.seq_uid limit 12
  ) d
  order by d.dist, d.seq_uid) select (select array_agg(seq_uid order by rank) from ties)=array['a','b'] tie_cutoff_ok, (select array_agg(seq_uid order by rank) from allrows)=array['a','b','c','z-near','a-far'] exact_order_and_exclusion_ok, (select count(*) from zero)=0 zero_ok,(select count(*) from missing)=0 missing_ok;
