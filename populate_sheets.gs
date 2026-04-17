// ============================================================
// DTN Experiment Results — Google Apps Script
// Paste this into: DTN Experiments sheet → Extensions → Apps Script
// Select populateDTNResults in the function dropdown, then click Run
// ============================================================

function populateDTNResults() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();

  var hdr = [["Label","Mode","WiFi_P","LTE_P","N_Pkts","Avg_ms","P50_ms","P95_ms","Max_ms","PDR_pct","DMiss_pct","Switchovers","Dur_s"]];

  // ── Exp 1 – Baseline (P0 / P0) ──────────────────────────────
  var sh1 = ss.getSheetByName("Exp 1 - Baseline");
  sh1.clearContents();
  var d1 = [
    ["E1_WiFi_T1",    "single_link_wifi","P0","P0", 47,  90.8, 80.8,152.0,186.7,100,  0,0,50.3],
    ["E1_WiFi_T2",    "single_link_wifi","P0","P0", 54, 100.3, 84.7,158.8,169.8,100,  0,0,58.0],
    ["E1_WiFi_T3",    "single_link_wifi","P0","P0", 47,  82.2, 76.4,135.2,159.1,100,  0,0,50.9],
    ["E1_LTE_T1",     "single_link_lte", "P0","P0", 49,  56.1, 44.9,117.2,226.7,100,  0,1,52.4],
    ["E1_LTE_T2",     "single_link_lte", "P0","P0", 48,  58.8, 44.8,146.8,333.3, 98,  0,0,50.6],
    ["E1_LTE_T3",     "single_link_lte", "P0","P0", 49,  54.6, 43.4,165.9,193.8,100,  0,0,52.7],
    ["E1_Adaptive_T1","adaptive",        "P0","P0", 47,  54.8, 43.1,123.2,167.0,100,  0,0,50.2],
    ["E1_Adaptive_T2","adaptive",        "P0","P0", 50,  56.2, 42.6,116.0,292.8,100,  0,0,53.3],
    ["E1_Adaptive_T3","adaptive",        "P0","P0", 57,  52.3, 42.6,101.5,107.1,100,  0,0,60.2],
    ["E1_Redundant_T1-3","redundant",    "P0","P0","N/A","skipped_aap_nack","","","","","","",""]
  ];
  sh1.getRange(1,1,1,13).setValues(hdr);
  sh1.getRange(2,1,d1.length,13).setValues(d1);
  sh1.getRange(1,1,1,13).setFontWeight("bold").setBackground("#4a86e8").setFontColor("#ffffff");

  // Summary block
  sh1.getRange(13,1,1,10).setValues([["SUMMARY","Mode","WiFi_P","LTE_P","Trials","Mean_Avg_ms","Std_ms","Mean_P50_ms","Mean_P95_ms","Mean_PDR_pct"]]);
  sh1.getRange(14,1,3,10).setValues([
    ["E1_WiFi",     "single_link_wifi","P0","P0",3, 91.1,7.4, 80.6,148.7,100.0],
    ["E1_LTE",      "single_link_lte", "P0","P0",3, 56.5,1.8, 44.4,143.3, 99.3],
    ["E1_Adaptive", "adaptive",        "P0","P0",3, 54.4,1.6, 42.8,113.6,100.0]
  ]);
  sh1.getRange(13,1,1,10).setFontWeight("bold").setBackground("#93c47d");
  sh1.autoResizeColumns(1,13);

  // ── Exp 5 – Full Compare (P5 WiFi / P0 LTE) ─────────────────
  var sh5 = ss.getSheetByName("Exp 5 - Full Compare");
  sh5.clearContents();
  var d5 = [
    ["E5_WiFi_T1",    "single_link_wifi","P5","P0", 51,  59.4, 58.3, 85.2,146.2, 98.1,0,0,54.7],
    ["E5_WiFi_T2",    "single_link_wifi","P5","P0", 52,  62.2, 64.7, 72.5, 72.8,100.0,0,1,54.4],
    ["E5_WiFi_T3",    "single_link_wifi","P5","P0", 53,  70.4, 73.1, 79.9, 82.1,100.0,0,0,56.4],
    ["E5_LTE_T1",     "single_link_lte", "P5","P0", 51,  78.4, 80.8, 86.1, 98.8, 98.1,0,1,54.5],
    ["E5_LTE_T2",     "single_link_lte", "P5","P0", 67,  87.1, 88.5, 94.9,115.4,100.0,0,0,71.3],
    ["E5_LTE_T3",     "single_link_lte", "P5","P0", 42,  94.3, 98.7,106.2,108.5,100.0,0,0,45.0],
    ["E5_Adaptive_T1","adaptive",        "P5","P0", 41, 101.3,102.1,107.4,110.1,100.0,0,0,43.0],
    ["E5_Adaptive_T2","adaptive",        "P5","P0", 40, 102.3,104.5,112.5,113.1,100.0,0,1,42.4],
    ["E5_Adaptive_T3","adaptive",        "P5","P0", 41, 107.3,108.2,114.3,122.4, 97.6,0,0,43.8],
    ["E5_Redundant_T1-3","redundant",    "P5","P0","N/A","skipped_aap_nack","","","","","","",""]
  ];
  sh5.getRange(1,1,1,13).setValues(hdr);
  sh5.getRange(2,1,d5.length,13).setValues(d5);
  sh5.getRange(1,1,1,13).setFontWeight("bold").setBackground("#4a86e8").setFontColor("#ffffff");

  sh5.getRange(13,1,1,10).setValues([["SUMMARY","Mode","WiFi_P","LTE_P","Trials","Mean_Avg_ms","Std_ms","Mean_P50_ms","Mean_P95_ms","Mean_PDR_pct"]]);
  sh5.getRange(14,1,3,10).setValues([
    ["E5_WiFi",     "single_link_wifi","P5","P0",3, 64.0,4.6, 65.4, 79.2,99.4],
    ["E5_LTE",      "single_link_lte", "P5","P0",3, 86.6,6.6, 89.3, 95.7,99.4],
    ["E5_Adaptive", "adaptive",        "P5","P0",3,103.6,2.5,104.9,111.4,99.2]
  ]);
  sh5.getRange(13,1,1,10).setFontWeight("bold").setBackground("#93c47d");
  sh5.autoResizeColumns(1,13);

  // ── Dashboard summary ────────────────────────────────────────
  var dash = ss.getSheetByName("Dashboard");
  if(dash) {
    // Find first empty row or clear existing summary area
    dash.getRange("A1:I20").clearContents();
    dash.getRange(1,1,1,9).setValues([["Condition","Mode","WiFi_P","LTE_P","Mean_Avg_ms","Mean_P50_ms","Mean_P95_ms","Mean_PDR_pct","Status"]]);
    dash.getRange(2,1,8,9).setValues([
      ["E1_WiFi_baseline",    "single_link_wifi","P0","P0", 91.1, 80.6,148.7,100.0,"complete"],
      ["E1_LTE_baseline",     "single_link_lte", "P0","P0", 56.5, 44.4,143.3, 99.3,"complete"],
      ["E1_Adaptive_baseline","adaptive",        "P0","P0", 54.4, 42.8,113.6,100.0,"complete"],
      ["E1_Redundant_baseline","redundant",      "P0","P0",   "",   "",  "",   "","pending_pi_restart"],
      ["E5_WiFi",             "single_link_wifi","P5","P0", 64.0, 65.4, 79.2, 99.4,"complete"],
      ["E5_LTE",              "single_link_lte", "P5","P0", 86.6, 89.3, 95.7, 99.4,"complete"],
      ["E5_Adaptive",         "adaptive",        "P5","P0",103.6,104.9,111.4, 99.2,"complete"],
      ["E5_Redundant",        "redundant",       "P5","P0",   "",   "",  "",   "","pending_pi_restart"]
    ]);
    dash.getRange(1,1,1,9).setFontWeight("bold").setBackground("#4a86e8").setFontColor("#ffffff");
    dash.autoResizeColumns(1,9);
  }

  SpreadsheetApp.flush();
  Logger.log("populateDTNResults complete — Exp1 and Exp5 data written.");
}
