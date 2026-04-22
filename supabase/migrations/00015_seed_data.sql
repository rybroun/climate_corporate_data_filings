-- Seed 6 sample companies from the design handoff

INSERT INTO company (canonical_name, legal_name, ticker, hq_country, is_public, wikidata_qid, aliases) VALUES
  ('Nestlé S.A.',              'Nestlé S.A.',              'NESN.SW',  'CH', true,  'Q80993',   ARRAY['Nestle', 'Nestlé']),
  ('Danone S.A.',              'Danone S.A.',              'BN.PA',    'FR', true,  'Q159476',  ARRAY['Danone', 'Groupe Danone']),
  ('Cargill, Incorporated',    'Cargill, Incorporated',    NULL,       'US', false, 'Q640302',  ARRAY['Cargill']),
  ('Unilever PLC',             'Unilever PLC',             'ULVR.L',   'GB', true,  'Q216149',  ARRAY['Unilever']),
  ('PepsiCo, Inc.',            'PepsiCo, Inc.',            'PEP',      'US', true,  'Q193540',  ARRAY['PepsiCo', 'Pepsi']),
  ('Mondelēz International',   'Mondelēz International, Inc.', 'MDLZ', 'US', true,  'Q4827038', ARRAY['Mondelez', 'Mondelēz']);
