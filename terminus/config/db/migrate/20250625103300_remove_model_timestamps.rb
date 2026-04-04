# frozen_string_literal: true

ROM::SQL.migration do
  change do
    drop_column :model, :created_at
    drop_column :model, :updated_at
  end
end
