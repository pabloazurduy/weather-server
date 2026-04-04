# frozen_string_literal: true

ROM::SQL.migration do
  change do
    alter_table :devices do
      add_foreign_key :model_id, :model, on_update: :cascade, on_delete: :cascade
      add_foreign_key :playlist_id, :playlist, on_update: :cascade, on_delete: :set_null
    end
  end
end
