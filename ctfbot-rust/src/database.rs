use rusqlite::{Connection, Result};
use serenity::model::id::{MessageId, RoleId};

pub fn init_db() -> Result<Connection> {
    let conn = Connection::open("ctfbot.db")?;
    conn.execute(
        "CREATE TABLE IF NOT EXISTS reaction_roles (
            message_id TEXT NOT NULL,
            role_id TEXT NOT NULL,
            emoji TEXT NOT NULL,
            PRIMARY KEY (message_id, emoji)
        )",
        [],
    )?;
    conn.execute(
        "CREATE TABLE IF NOT EXISTS alpacahack_users (name TEXT NOT NULL UNIQUE)",
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

pub fn insert_alpacahack_user(conn: &Connection, name: &str) -> Result<String> {
    conn.execute("INSERT INTO alpacahack_users (name) VALUES (?1)", [name])?;
    Ok(format!("Added user: {}", name))
}

pub fn delete_alpacahack_user(conn: &Connection, name: &str) -> Result<String> {
    conn.execute("DELETE FROM alpacahack_users WHERE name = ?1", [name])?;
    Ok(format!("Deleted user: {}", name))
}

pub fn get_all_alpacahack_users(conn: &Connection) -> Result<Vec<String>> {
    let mut stmt = conn.prepare("SELECT name FROM alpacahack_users")?;
    let mut rows = stmt.query([])?;
    let mut users = Vec::new();
    while let Some(row) = rows.next()? {
        users.push(row.get(0)?);
    }
    Ok(users)
}
