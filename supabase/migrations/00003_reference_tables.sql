-- Reference tables: GHG Protocol categories and emissions category tags

CREATE TABLE ghg_protocol_category (
  ghg_code    TEXT PRIMARY KEY,
  scope       INT NOT NULL,
  category_number INT,  -- NULL for Scope 1 and Scope 2
  name        TEXT NOT NULL,
  typical_activities TEXT,
  standard_version TEXT NOT NULL DEFAULT '2011_corporate_value_chain',
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE emissions_category_tag (
  tag_code    TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  description TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed GHG Protocol categories
INSERT INTO ghg_protocol_category (ghg_code, scope, category_number, name, typical_activities) VALUES
  ('s1',     1, NULL, 'Direct Emissions', 'Owned fuel combustion, fleet, process emissions, fugitive emissions'),
  ('s2_loc', 2, NULL, 'Scope 2 Location-Based', 'Purchased electricity, steam, heating, cooling (grid-average factors)'),
  ('s2_mkt', 2, NULL, 'Scope 2 Market-Based', 'Purchased electricity, steam, heating, cooling (contractual instruments)'),
  ('s3_1',   3, 1,  'Purchased Goods & Services', 'Cradle-to-gate emissions of purchased goods and services'),
  ('s3_2',   3, 2,  'Capital Goods', 'Cradle-to-gate emissions of capital goods'),
  ('s3_3',   3, 3,  'Fuel- and Energy-Related Activities', 'Upstream emissions of purchased fuels and electricity not in Scope 1/2'),
  ('s3_4',   3, 4,  'Upstream Transportation & Distribution', 'Transportation and distribution of purchased products'),
  ('s3_5',   3, 5,  'Waste Generated in Operations', 'Disposal and treatment of waste generated in operations'),
  ('s3_6',   3, 6,  'Business Travel', 'Employee business travel'),
  ('s3_7',   3, 7,  'Employee Commuting', 'Employee commuting and remote working'),
  ('s3_8',   3, 8,  'Upstream Leased Assets', 'Emissions from leased assets not in Scope 1/2'),
  ('s3_9',   3, 9,  'Downstream Transportation & Distribution', 'Transportation and distribution of sold products'),
  ('s3_10',  3, 10, 'Processing of Sold Products', 'Processing of intermediate products by downstream companies'),
  ('s3_11',  3, 11, 'Use of Sold Products', 'End-use of goods and services sold'),
  ('s3_12',  3, 12, 'End-of-Life Treatment of Sold Products', 'Waste disposal and treatment of sold products'),
  ('s3_13',  3, 13, 'Downstream Leased Assets', 'Emissions from assets leased to other entities'),
  ('s3_14',  3, 14, 'Franchises', 'Emissions from franchise operations'),
  ('s3_15',  3, 15, 'Investments', 'Emissions from equity and debt investments');

-- Seed emissions category tags
INSERT INTO emissions_category_tag (tag_code, name, description) VALUES
  ('flag',                       'FLAG',                       'Forest, Land and Agriculture emissions'),
  ('biogenic',                   'Biogenic',                   'CO2 emissions from biogenic sources'),
  ('removals',                   'Removals',                   'Carbon dioxide removals'),
  ('outside_reporting_boundary', 'Outside Reporting Boundary', 'Emissions outside the organizational reporting boundary');
