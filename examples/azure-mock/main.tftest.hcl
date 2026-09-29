mock_provider "azurerm" {
  override_during = plan
}

run "create_plan" {
  command = plan
}

run "create_state" {
  command = apply
}

run "upgrade_plan" {
  command = plan
  variables {
    vm_size = "Standard_B2s"
  }
}

run "delete_plan" {
  command = plan
  variables {
    vm_count = 0
  }
}
