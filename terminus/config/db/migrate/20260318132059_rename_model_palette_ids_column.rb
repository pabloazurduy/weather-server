# frozen_string_literal: true

ROM::SQL.migration { change { rename_column :model, :palette_ids, :palette_names } }
