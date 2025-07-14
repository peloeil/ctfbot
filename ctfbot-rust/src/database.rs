use rusqlite::{Connection, Result};
use serenity::model::id::{MessageId, RoleId};

pub fn init_db() -> Result<Connection> {
    let conn = Connection::open("database.sqlite")?;
    conn.execute(
        "CREATE TABLE IF NOT EXISTS reaction_roles (
            message_id TEXT NOT NULL,
            role_id TEXT NOT NULL,
            emoji TEXT NOT NULL,
            PRIMARY KEY (message_id, emoji)
        )",
        [],
    )?;
    Ok(conn)
}

pub fn add_reaction_role(conn: &Connection, message_id: MessageId, role_id: RoleId, emoji: &str) -> Result<()> {
    conn.execute(
        "INSERT INTO reaction_roles (message_id, role_id, emoji) VALUES (?1, ?2, ?3)",
        &[&message_id.to_string(), &role_id.to_string(), emoji],
    )?;
    Ok(())
}

pub fn remove_reaction_role(conn: &Connection, message_id: MessageId, emoji: &str) -> Result<()> {
    conn.execute(
        "DELETE FROM reaction_roles WHERE message_id = ?1 AND emoji = ?2",
        &[&message_id.to_string(), emoji],
    )?;
    Ok(())
}

pub fn get_reaction_role(conn: &Connection, message_id: MessageId, emoji: &str) -> Result<Option<RoleId>> {
    let mut stmt = conn.prepare("SELECT role_id FROM reaction_roles WHERE message_id = ?1 AND emoji = ?2")?;
    let mut rows = stmt.query(&[&message_id.to_string(), emoji])?;

    if let Some(row) = rows.next()? {
        let role_id_str: String = row.get(0)?;
        let role_id = RoleId::new(role_id_str.parse().unwrap());
        Ok(Some(role_id))
    } else {
        Ok(None)
    }
}
