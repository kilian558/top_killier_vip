module.exports = {
  apps: [
    {
      name: 'top-killer-vip',
      script: 'top_killer_vip.py',
      interpreter: 'python3',
      
      // Automatischer Restart bei Absturz
      autorestart: true,
      
      // Max. 10 Restart-Versuche
      max_restarts: 10,
      
      // Warte 5 Sekunden zwischen Restarts
      restart_delay: 5000,
      
      // Restart bei Speicherlimit (optional)
      max_memory_restart: '500M',
      
      // Logging
      error_file: './logs/error.log',
      out_file: './logs/output.log',
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      
      // Kombiniere Logs
      combine_logs: true,
      
      // Merge Cluster-Logs (falls nötig)
      merge_logs: true,
      
      // Environment
      env: {
        NODE_ENV: 'production',
      },
      
      // Kein Watch-Mode (für Produktion)
      watch: false,
      
      // Ignoriere bestimmte Dateien beim Watch (falls aktiviert)
      ignore_watch: ['node_modules', 'logs', 'data', '.git'],
      
      // Instanzen (1 = single instance)
      instances: 1,
      exec_mode: 'fork'
    }
  ]
};
