using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

static class Launcher {
    [STAThread]
    static void Main(string[] args) {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        try {
            string profile=Environment.GetEnvironmentVariable("AC_TEST_PROFILE");
            if(String.IsNullOrEmpty(profile)) profile=Path.Combine(root,"userdata");
            // Recover a power-interrupted replacement using the independent helper runtime.
            string updates=Path.Combine(profile,"updates");
            if(File.Exists(Path.Combine(updates,"install-journal.json"))) {
                string helper=Path.Combine(updates,"helper-runtime");
                var recovery=new ProcessStartInfo(Path.Combine(helper,"pythonw.exe"));
                recovery.Arguments="\""+Path.Combine(helper,"update_engine.py")+"\" --recover \""+Path.Combine(updates,"install-plan.json")+"\"";
                recovery.UseShellExecute=false;recovery.CreateNoWindow=true;
                Process.Start(recovery);return;
            }
            var info = new ProcessStartInfo(Path.Combine(root,"runtime","pythonw.exe"));
            info.Arguments = "\"" + Path.Combine(root,"app","portable_entry.py") + "\"";
            info.WorkingDirectory = root;
            info.UseShellExecute = false;
            info.CreateNoWindow = true;
            // The portable version must never inherit the publisher's profile or credentials.
            foreach (string key in new [] {"AH_ADDON","AH_PROFILE","AH_STASHDB_KEY","AH_FANSDB_KEY","AH_TPDB_KEY","AH_PORT","AH_MEDIA_PORT"})
                info.EnvironmentVariables.Remove(key);
            string ready=Path.Combine(profile,"startup.ready");
            DateTime start=DateTime.UtcNow;
            var process=Process.Start(info);
            var form=new Form {Text="Adult Client · Start",Width=560,Height=205,StartPosition=FormStartPosition.CenterScreen,MaximizeBox=false,FormBorderStyle=FormBorderStyle.FixedDialog};
            var label=new Label {Text="Adult Client wird gestartet / Starting Adult Client …\n\nBeim ersten Start werden die Modelldaten vorbereitet.\nModel data is prepared on first launch.\n\nDer Browser öffnet sich automatisch. / Your browser opens automatically.",Dock=DockStyle.Fill,Padding=new Padding(18),AutoSize=false};
            form.Controls.Add(label);
            var timer=new Timer {Interval=500};
            timer.Tick+=(sender,e)=> {
                if(process.HasExited || (File.Exists(ready) && File.GetLastWriteTimeUtc(ready)>=start.AddSeconds(-1))) {timer.Stop();form.Close();}
            };
            timer.Start();Application.Run(form);
        } catch (Exception error) {
            MessageBox.Show("Start fehlgeschlagen. Bitte das gesamte ZIP entpacken.\nStartup failed. Please extract the entire ZIP archive.\n\n"+error.Message,"Adult Client",MessageBoxButtons.OK,MessageBoxIcon.Error);
        }
    }
}
