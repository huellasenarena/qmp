function onOpen() {
  DocumentApp.getUi().createMenu('Sheet Controls')
      .addItem('Open Data Entry Panel', 'showSidebar')
      .addToUi();
}

function addDataToSheet(newEntry) {
  var sheet = SpreadsheetApp.openById("YOUR_SHEET_ID").getActiveSheet();
  sheet.appendRow([newEntry]);
  // This adds the data from your Doc sidebar into the Sheet
}

function refreshTable() {
  // This command forces the linked objects in the Doc to sync
  // so you see the new "Random" value immediately.
}