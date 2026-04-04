# frozen_string_literal: true

ROM::SQL.migration do
  change do
    create_enum :palette_kind, %w[trmnl terminus]

    create_table :palette do
      primary_key :id

      column :name, String, unique: true, null: false
      column :label, String, null: false
      column :kind, :palette_kind, index: true, null: false, default: "terminus"
      column :grays, :integer, null: false, default: 0
      column :colors, "text[]", null: false, default: "{}"
      column :framework_class, String
      column :created_at, :timestamp, null: false, default: Sequel::CURRENT_TIMESTAMP
      column :updated_at, :timestamp, null: false, default: Sequel::CURRENT_TIMESTAMP
    end
  end
end
