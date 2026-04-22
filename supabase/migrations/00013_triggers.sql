-- Auto-update updated_at on every write

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply to all tables with updated_at
DO $$
DECLARE
  tbl TEXT;
BEGIN
  FOR tbl IN
    SELECT unnest(ARRAY[
      'company', 'source_document', 'emissions_disclosure', 'emissions_line_item',
      'company_category_mapping', 'ghg_protocol_category', 'emissions_category_tag',
      'emissions_target', 'target_progress_snapshot', 'decarbonization_program',
      'sustainability_certification', 'data_provenance'
    ])
  LOOP
    EXECUTE format(
      'CREATE TRIGGER trg_%s_updated_at BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION update_updated_at()',
      tbl, tbl
    );
  END LOOP;
END;
$$;
