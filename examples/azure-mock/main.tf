terraform {
  required_version = ">= 1.7"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "= 4.67.0"
    }
  }
}

variable "vm_size" {
  type    = string
  default = "Standard_B1s"
}

variable "vm_count" {
  type    = number
  default = 1
}

resource "azurerm_resource_group" "demo" {
  name     = "costguard-demo-rg"
  location = "East US"
}

resource "azurerm_linux_virtual_machine" "app" {
  count                           = var.vm_count
  name                            = "costguard-demo-vm"
  resource_group_name             = azurerm_resource_group.demo.name
  location                        = azurerm_resource_group.demo.location
  size                            = var.vm_size
  admin_username                  = "demo_user"
  admin_password                  = "ExampleOnlyPassword123!"
  disable_password_authentication = false
  network_interface_ids           = ["/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/costguard-demo-rg/providers/Microsoft.Network/networkInterfaces/demo-nic"]

  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "Standard_LRS"
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "0001-com-ubuntu-server-jammy"
    sku       = "22_04-lts"
    version   = "latest"
  }
}

resource "azurerm_managed_disk" "data" {
  name                 = "costguard-demo-disk"
  location             = azurerm_resource_group.demo.location
  resource_group_name  = azurerm_resource_group.demo.name
  storage_account_type = "Premium_LRS"
  create_option        = "Empty"
  disk_size_gb         = 128
}
