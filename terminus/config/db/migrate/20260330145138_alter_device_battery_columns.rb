# frozen_string_literal: true

ROM::SQL.migration do
  change do
    rename_column :device, :battery, :battery_voltage
    add_column :device, :battery_charge, :float, null: false, default: 0
  end
end
