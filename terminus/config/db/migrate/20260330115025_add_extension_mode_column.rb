# frozen_string_literal: true

ROM::SQL.migration { change { add_column :extension, :mode, String, null: false, default: "text" } }
