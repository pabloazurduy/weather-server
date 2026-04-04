# frozen_string_literal: true

ROM::SQL.migration do
  change do
    create_table :model do
      primary_key :id

      column :name, String, unique: true, index: true, null: false
      column :label, String, unique: true, index: true, null: false
      column :description, :text
      column :width, Integer, null: false
      column :height, Integer, null: false
      column :published_at, :timestamp
      column :created_at, :timestamp, null: false, default: Sequel::CURRENT_TIMESTAMP
      column :updated_at, :timestamp, null: false, default: Sequel::CURRENT_TIMESTAMP
    end
  end
end
